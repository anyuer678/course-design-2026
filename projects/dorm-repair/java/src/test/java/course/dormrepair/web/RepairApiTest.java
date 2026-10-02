package course.dormrepair.web;

import course.dormrepair.RepairApplication;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 接口层真启动、真发 HTTP（RANDOM_PORT），不是 MockMvc 那种"假装发过请求"。
 * PLAN 第 6 节要求 Web 必须实际启动并交互验证正常路径、错误输入与回归。
 */
@SpringBootTest(classes = RepairApplication.class, webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class RepairApiTest {

    @Autowired
    private TestRestTemplate rest;

    @SuppressWarnings("unchecked")
    private Map<String, Object> body(ResponseEntity<Map> response) {
        return (Map<String, Object>) response.getBody();
    }

    private HttpHeaders json() {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        return headers;
    }

    private Map<String, Object> createOrder(String actor, String room, String category,
                                            String priority, String description, String contact) {
        ResponseEntity<Map> r = rest.postForEntity("/api/orders?role=STUDENT&actor=" + actor,
                new HttpEntity<>(Map.of("room", room, "category", category, "priority", priority,
                        "description", description, "contact", contact), json()), Map.class);
        assertEquals(HttpStatus.CREATED, r.getStatusCode(), r.getBody().toString());
        return body(r);
    }

    @SuppressWarnings("unchecked")
    private ResponseEntity<Map> act(String id, String action, String role, String actor,
                                    Map<String, Object> input, Integer graceHours) {
        String url = "/api/orders/" + id + "/actions/" + action + "?role=" + role + "&actor=" + actor
                + (graceHours == null ? "" : "&graceHours=" + graceHours);
        return rest.postForEntity(url, new HttpEntity<>(input, json()), Map.class);
    }

    @Test
    void happyPathGoesAllTheWayToClosed() {
        Map<String, Object> draft = createOrder("stu-9", "A01-109", "WATER_ELEC", "NORMAL",
                "水管漏水", "13800000009");
        String id = (String) draft.get("id");
        assertEquals("DRAFT", draft.get("state"));
        assertEquals(List.of("cancel", "submit"),
                ((List<String>) draft.get("attemptable")).stream().sorted().toList(),
                "草稿有两个按钮：提交（TR-01）与取消（TR-11），少一个就是表读歪了");

        assertEquals("SUBMITTED", act(id, "submit", "STUDENT", "stu-9", Map.of(), null).getBody().get("state"));
        Map<String, Object> assigned = body(act(id, "assign", "ADMIN", "adm-1",
                Map.of("assignee", "w-1"), null));
        assertEquals("w-1", assigned.get("assignee"));
        // 同一个 ASSIGNED 状态，两个角色看到的按钮不一样——这才是"判定源在模型"的证据
        assertEquals(List.of("cancel", "reassign", "return_pool"),
                ((List<String>) assigned.get("attemptable")).stream().sorted().toList(),
                "这是管理员视角：改派 / 退回 / 取消");
        Map<String, Object> workerView = body(rest.getForEntity(
                "/api/orders/" + id + "?role=WORKER&actor=w-1", Map.class));
        assertEquals(List.of("accept", "decline"),
                ((List<String>) workerView.get("attemptable")).stream().sorted().toList(),
                "这是被派到的维修员视角");
        assertEquals(List.of(), workerView.get("requiredInputs"),
                "接单与拒单都不需要额外填东西；要填什么是契约说了算，不是前端猜");
        Map<String, Object> inProgress = body(act(id, "accept", "WORKER", "w-1", Map.of(), null));
        assertEquals(List.of("note"), inProgress.get("requiredInputs"),
                "到了 IN_PROGRESS，完工就必须写说明（TR-07 的 resolution_note）");

        act(id, "resolve", "WORKER", "w-1", Map.of("note", "换了垫圈"), null);
        Map<String, Object> closed = body(act(id, "confirm", "STUDENT", "stu-9", Map.of(), null));
        assertEquals("CLOSED", closed.get("state"));
        assertEquals("", closed.get("assignee"), "终态不挂当前负责人");
        assertEquals("w-1", closed.get("resolvedBy"), "但处理人留着（BR-11）");
        assertEquals(5, ((List<?>) closed.get("history")).size());
        assertEquals(List.of(), closed.get("attemptable"), "终态没有任何可点动作");
    }

    @Test
    void badFieldsAreReportedAllAtOnce() {
        int before = visibleIds("STUDENT", "stu-8").size();
        ResponseEntity<Map> r = rest.postForEntity(
                "/api/orders?role=STUDENT&actor=stu-8",
                new HttpEntity<>(Map.of("room", "no-such", "category", "SPACECRAFT",
                        "priority", "NORMAL", "description", "   ", "contact", "123"), json()), Map.class);
        assertEquals(HttpStatus.BAD_REQUEST, r.getStatusCode(), r.getBody().toString());
        Map<String, Object> payload = body(r);
        assertEquals("INVALID_FIELDS", payload.get("error"));
        List<Map<String, String>> fields = (List<Map<String, String>>) payload.get("fields");
        List<String> names = fields.stream().map(f -> f.get("field")).toList();
        assertTrue(names.containsAll(List.of("room", "category", "description", "contact")),
                "一次报全（FR-03）：实际只报了 " + names);
        assertEquals(4, fields.size(), "四个字段都违规，就该一次给四条，不是给第一条");
        assertEquals(before, visibleIds("STUDENT", "stu-8").size(),
                "校验失败不许留下半成品工单（NFR-03）");
    }

    @Test
    void overPermissionIsRefusedAndChangesNothing() {
        String id = (String) createOrder("stu-7", "A01-107", "NETWORK", "URGENT",
                "网口断", "13800000007").get("id");
        act(id, "submit", "STUDENT", "stu-7", Map.of(), null);

        // ① 状态里有这个动作、但角色不对 → 403（assign 只在 SUBMITTED 存在，且只给 ADMIN）
        ResponseEntity<Map> stolen = act(id, "assign", "WORKER", "w-9",
                Map.of("assignee", "w-9"), null);
        assertEquals(HttpStatus.FORBIDDEN, stolen.getStatusCode(), stolen.getBody().toString());
        assertEquals("ROLE_NOT_ALLOWED", body(stolen).get("error"));

        // ② 角色对、但这个状态下没有这个动作 → 400，不是 403。
        //    两者能区分开很重要：403 会说"权限模型在管"，400 会说"流程根本不该这样走"。
        ResponseEntity<Map> wrongState = act(id, "accept", "WORKER", "w-9", Map.of(), null);
        assertEquals(HttpStatus.BAD_REQUEST, wrongState.getStatusCode(), wrongState.getBody().toString());
        assertEquals("NO_SUCH_TRANSITION", body(wrongState).get("error"));

        // ③ 状态与角色都对、但不是本人 → 409（先把单推到 RESOLVED，再让另一个学生验收）
        act(id, "assign", "ADMIN", "adm-1", Map.of("assignee", "w-1"), null);
        act(id, "accept", "WORKER", "w-1", Map.of(), null);
        act(id, "resolve", "WORKER", "w-1", Map.of("note", "重启了交换机"), null);
        ResponseEntity<Map> notYours = act(id, "confirm", "STUDENT", "stu-other", Map.of(), null);
        assertEquals(HttpStatus.CONFLICT, notYours.getStatusCode(), notYours.getBody().toString());
        assertEquals("OWNER", body(notYours).get("error"));

        Map<String, Object> still = body(rest.getForEntity(
                "/api/orders/" + id + "?role=ADMIN&actor=adm-1", Map.class));
        assertEquals("RESOLVED", still.get("state"), "被拒的转换不许留下任何痕迹");
        assertEquals(4, ((List<?>) still.get("history")).size(),
                "submit/assign/accept/resolve 四条，被拒的三次 attempt 一条都没进");
    }

    @Test
    void forceCloseNeedsTheGracePeriodButAcceptsAConfiguredOne() {
        String id = (String) createOrder("stu-6", "A01-106", "FURNITURE", "LOW",
                "书桌抽屉卡住", "13800000006").get("id");
        act(id, "submit", "STUDENT", "stu-6", Map.of(), null);
        act(id, "assign", "ADMIN", "adm-1", Map.of("assignee", "w-1"), null);
        act(id, "accept", "WORKER", "w-1", Map.of(), null);
        act(id, "resolve", "WORKER", "w-1", Map.of("note", "上了油"), null);

        ResponseEntity<Map> early = act(id, "force_close", "ADMIN", "adm-1", Map.of(), null);
        assertEquals(HttpStatus.CONFLICT, early.getStatusCode(), early.getBody().toString());
        assertEquals("ACCEPTANCE_NOT_MATURE", body(early).get("error"), "AC-24：刚完工就关应当被拒");
        // 视图标志与判定同口径：后端拒的时候，界面也不许说"可以关了"
        Map<String, Object> view = body(rest.getForEntity(
                "/api/orders/" + id + "?role=ADMIN&actor=adm-1", Map.class));
        assertEquals(Boolean.FALSE, view.get("acceptanceStale"),
                "acceptanceStale 为真才允许强制关闭——两者口径必须一致");

        Map<String, Object> closed = body(act(id, "force_close", "ADMIN", "adm-1", Map.of(), 0));
        assertEquals("CLOSED", closed.get("state"), "阈值是配置项：宽限 0 小时时同一时刻就允许");
    }

    @Test
    void workerHistoryVisibilityOverHttp() {
        String id = (String) createOrder("stu-5", "A01-105", "OTHER", "NORMAL",
                "门吸掉了", "13800000005").get("id");
        act(id, "submit", "STUDENT", "stu-5", Map.of(), null);
        act(id, "assign", "ADMIN", "adm-1", Map.of("assignee", "w-1"), null);
        act(id, "accept", "WORKER", "w-1", Map.of(), null);
        act(id, "resolve", "WORKER", "w-1", Map.of("note", "重新粘好"), null);
        act(id, "confirm", "STUDENT", "stu-5", Map.of(), null);

        List<String> w1 = visibleIds("WORKER", "w-1");
        assertTrue(w1.contains(id), "AQ-12：修过的人看得见自己那张历史单");
        assertFalse(visibleIds("WORKER", "w-2").contains(id), "别人的历史不进我的列表");
        Map<String, Object> view = body(rest.getForEntity(
                "/api/orders/" + id + "?role=WORKER&actor=w-1", Map.class));
        assertEquals(List.of(), view.get("attemptable"), "看得见，但点不动");
    }

    @Test
    void draftsStayOutOfTheWorkerPoolOverHttp() {
        String id = (String) createOrder("stu-4", "A01-104", "WATER_ELEC", "NORMAL",
                "想到再补", "13800000004").get("id");
        assertFalse(visibleIds("WORKER", "w-1").contains(id), "草稿不进公共池（AQ-07）");
        assertTrue(visibleIds("STUDENT", "stu-4").contains(id));
        assertEquals(HttpStatus.NOT_FOUND, rest.getForEntity(
                "/api/orders/" + id + "?role=WORKER&actor=w-1", Map.class).getStatusCode(),
                "越权读取与不存在返回同一个码：不额外透露这张单存在但你不能看");
    }

    @Test
    void unknownIdAndUnknownRoleFailLoudly() {
        assertEquals(HttpStatus.NOT_FOUND, rest.getForEntity(
                "/api/orders/NOPE?role=ADMIN&actor=adm-1", Map.class).getStatusCode());
        ResponseEntity<Map> bad = act("NOPE", "submit", "CURATOR", "x", Map.of(), null);
        assertEquals(HttpStatus.BAD_REQUEST, bad.getStatusCode(), bad.getBody().toString());
        assertEquals("BAD_IDENTITY", body(bad).get("error"));
    }

    @Test
    void listAndDetailAgreeOnHistory() {
        // 同一个字段不许有两种含义：列表曾经固定返回空 history，
        // 于是"已关闭"的单在列表里看起来一步都没走过。
        String id = (String) createOrder("stu-3", "A01-103", "OTHER", "NORMAL",
                "床梯松动", "13800000003").get("id");
        act(id, "submit", "STUDENT", "stu-3", Map.of(), null);
        act(id, "assign", "ADMIN", "adm-1", Map.of("assignee", "w-1"), null);
        act(id, "accept", "WORKER", "w-1", Map.of(), null);
        act(id, "resolve", "WORKER", "w-1", Map.of("note", "拧紧螺栓"), null);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> listed =
                (List<Map<String, Object>>) body(rest.getForEntity(
                        "/api/orders?role=ADMIN&actor=adm-1", Map.class)).get("orders");
        Map<String, Object> inList = listed.stream()
                .filter(o -> o.get("id").equals(id)).findFirst().orElseThrow();
        Map<String, Object> inDetail = body(rest.getForEntity(
                "/api/orders/" + id + "?role=ADMIN&actor=adm-1", Map.class));
        assertEquals(((List<?>) inDetail.get("history")).size(),
                ((List<?>) inList.get("history")).size(),
                "列表与详情的留痕条数必须一致");
        assertEquals(4, ((List<?>) inList.get("history")).size());
    }

    @SuppressWarnings("unchecked")
    private List<String> visibleIds(String role, String actor) {
        Map<String, Object> payload = body(rest.getForEntity(
                "/api/orders?role=" + role + "&actor=" + actor, Map.class));
        List<Map<String, Object>> orders = (List<Map<String, Object>>) payload.get("orders");
        return orders.stream().map(o -> (String) o.get("id")).toList();
    }
}

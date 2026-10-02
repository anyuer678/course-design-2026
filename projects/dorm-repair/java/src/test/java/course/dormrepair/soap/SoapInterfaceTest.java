package course.dormrepair.soap;

import course.dormrepair.RepairApplication;
import course.dormrepair.contract.WorkflowContract;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.w3c.dom.Document;
import org.w3c.dom.NodeList;

import javax.xml.parsers.DocumentBuilderFactory;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 本轮的落脚点：**两种接口，一份规则**。
 *
 * 断言的形状是"同一批数据、同一组身份，REST 与 SOAP 必须给出同样的可见集合、
 * 同样的按钮、同样的错误码"。只要有人在 SOAP 层另写一套判断（哪怕只是"草稿不给维修员看"
 * 这种看起来人畜无害的复制），这两边的结果就会分叉——而分叉是可以被精确抓出来的。
 */
@SpringBootTest(classes = RepairApplication.class, webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class SoapInterfaceTest {

    @Autowired
    private TestRestTemplate rest;

    @Autowired
    private WorkflowContract contract;

    private String create(String student, String room, String category) {
        ResponseEntity<Map> r = rest.postForEntity("/api/orders?role=STUDENT&actor=" + student,
                new HttpEntity<>(Map.of("room", room, "category", category, "priority", "NORMAL",
                        "description", "d", "contact", "13800000000"), json()), Map.class);
        return (String) r.getBody().get("id");
    }

    private void act(String id, String action, String role, String actor, Map<String, Object> input) {
        rest.postForEntity("/api/orders/" + id + "/actions/" + action + "?role=" + role + "&actor=" + actor,
                new HttpEntity<>(input, json()), Map.class);
    }

    private HttpHeaders json() {
        HttpHeaders h = new HttpHeaders();
        h.setContentType(MediaType.APPLICATION_JSON);
        return h;
    }

    @Test
    void restAndSoapReturnTheSameVisibleIds() {
        String pool = create("stu-p1", "A01-201", "WATER_ELEC");            // 提交后停在公共池
        act(pool, "submit", "STUDENT", "stu-p1", Map.of());                 // 上一版忘了这步，于是它是草稿
        String mine = create("stu-p1", "A01-202", "NETWORK");
        act(mine, "submit", "STUDENT", "stu-p1", Map.of());
        act(mine, "assign", "ADMIN", "adm-1", Map.of("assignee", "w-1"));
        String draft = create("stu-p2", "A01-203", "OTHER");                 // 别人的草稿

        for (String[] who : List.of(new String[]{"STUDENT", "stu-p1"},
                new String[]{"STUDENT", "stu-p2"},
                new String[]{"WORKER", "w-1"}, new String[]{"WORKER", "w-9"},
                new String[]{"ADMIN", "adm-1"})) {
            List<String> viaRest = restIds(who[0], who[1]);
            List<String> viaSoap = soapIds(who[0], who[1]);
            assertEquals(viaRest, viaSoap, who[0] + "/" + who[1] + " 两种接口的可见集合必须相同");
            // 且这份集合本身是可信的：草稿不进维修员、公共池进维修员
            if (who[0].equals("WORKER")) {
                assertFalse(viaSoap.contains(draft), "草稿不该被维修员看见（AQ-07）");
                assertTrue(viaSoap.contains(pool), "公共池必须可见");
            }
        }
        assertTrue(soapIds("WORKER", "w-1").contains(mine), "派给他的单在 SOAP 里也在");
        assertFalse(soapIds("WORKER", "w-9").contains(mine), "派给别人就不该出现");
    }

    @Test
    void sameIdentitySameButtons() {
        String id = create("stu-b1", "A01-210", "FURNITURE");
        act(id, "submit", "STUDENT", "stu-b1", Map.of());
        act(id, "assign", "ADMIN", "adm-1", Map.of("assignee", "w-1"));

        @SuppressWarnings("unchecked")
        List<String> restActions = (List<String>) rest.getForEntity(
                "/api/orders/" + id + "?role=WORKER&actor=w-1", Map.class).getBody().get("attemptable");
        List<String> soapActions = soapOrder(id, "WORKER", "w-1").actions;
        assertEquals(sorted(restActions), sorted(soapActions),
                "按钮集合两边必须一致：它只可能来自契约，不该有两个来源");
        assertTrue(sorted(soapActions).contains("accept"));
        assertFalse(soapActions.contains("resolve"), "还没接单就不能完工");
    }

    @Test
    void sameRejectionCodeOnBothInterfaces() {
        // 只对**两边都有的操作**比错误码。本 SOAP 接口只提供 UC-05 的查询（docs/10 第 2 节），
        // 上一版我朝它发了 <Assign>，拿到 CLIENT 是对的——那不该算进"同一码"的断言里。
        String id = create("stu-c1", "A01-211", "WATER_ELEC");
        act(id, "submit", "STUDENT", "stu-c1", Map.of());
        act(id, "assign", "ADMIN", "adm-1", Map.of("assignee", "w-1"));

        // ① 身份非法：两种接口都给同一个码
        String restCode = String.valueOf(rest.getForEntity("/api/orders?role=CURATOR&actor=x", Map.class)
                .getBody().get("error"));
        String soapCode = SoapEnvelope.faultCodeOf(soapRaw(
                "<ListOrders><Role>CURATOR</Role><Actor>x</Actor></ListOrders>"));
        assertEquals("BAD_IDENTITY", restCode);
        assertEquals(restCode, soapCode, "两份接口对同一件事说了两个码，就没人能信任错误处理了");

        // ② 越权读取：REST 404 / SOAP Fault，语义一致——都不透露"它存在"
        assertEquals("NOT_FOUND", SoapEnvelope.faultCodeOf(soapRaw(
                "<GetOrder><Role>WORKER</Role><Actor>w-7</Actor><Id>" + id + "</Id></GetOrder>")));

        // ③ 判定结果（按钮）跨接口一致：w-1 能接单，w-9 连这张单都读不到
        List<String> w1Buttons = sorted(soapOrder(id, "WORKER", "w-1").actions());
        assertEquals(List.of("accept", "decline"), w1Buttons);
        assertEquals(sorted(restOrder(id, "WORKER", "w-1")), w1Buttons,
                "按钮集合两边必须一致：它只可能来自契约，不该有两个来源");
        // w-9 走 GetOrder 会拿到 Fault（NOT_FOUND），所以这里没有 Attemptable 元素——
        // 它不是"看见了但没按钮"，而是"根本看不见"
        assertEquals(List.of(), texts(soapRaw("<GetOrder><Role>WORKER</Role><Actor>w-9</Actor><Id>"
                + id + "</Id></GetOrder>"), "Attemptable"));
    }

    @Test
    void invisibleOrderIsNotFoundOnBothInterfaces() {
        String id = create("stu-d1", "A01-212", "OTHER");
        ResponseEntity<Map> http = rest.getForEntity("/api/orders/" + id + "?role=WORKER&actor=w-8",
                Map.class);
        assertTrue(http.getStatusCode().is4xxClientError(), "REST 越权读取按 404");
        String fault = soapRaw("<GetOrder><Role>WORKER</Role><Actor>w-8</Actor><Id>" + id
                + "</Id></GetOrder>");
        assertEquals("NOT_FOUND", SoapEnvelope.faultCodeOf(fault),
                "SOAP 侧同样不能透露这张单存在但你看不到");
    }

    @Test
    void unknownRoleIsRejectedIdentically() {
        ResponseEntity<Map> http = rest.getForEntity("/api/orders?role=CURATOR&actor=x", Map.class);
        assertEquals("BAD_IDENTITY", http.getBody().get("error"));
        String fault = soapRaw("<ListOrders><Role>CURATOR</Role><Actor>x</Actor></ListOrders>");
        assertEquals("BAD_IDENTITY", SoapEnvelope.faultCodeOf(fault));
    }

    @Test
    void wsdlEnumerationsComeFromTheContract() {
        String wsdl = rest.getForEntity("/api/soap/repair?wsdl", String.class).getBody();
        for (String state : contract.states()) {
            assertTrue(wsdl.contains("<xs:enumeration value=\"" + state + "\"/>"),
                    "WSDL 缺状态 " + state + "，说明描述文件与契约分叉了");
        }
        // 反向也查：WSDL 不许自己发明状态
        List<String> declared = enumerations(wsdl, "StateType");
        assertEquals(sorted(contract.states()), sorted(declared),
                "WSDL 的状态枚举必须逐字等于契约：" + declared);
        assertTrue(wsdl.contains("ACCEPTANCE_TIMEOUT".toLowerCase())
                        || enumerations(wsdl, "FaultCodeType").contains("acceptance_timeout"),
                "宽限期前置条件也要能在故障码里出现（BR-10）");
    }

    @Test
    void unknownOperationIsAClientFaultNotACrash() {
        String fault = soapRaw("<DoEverythingOnServer><Role>ADMIN</Role><Actor>adm-1</Actor>"
                + "</DoEverythingOnServer>");
        assertEquals("CLIENT", SoapEnvelope.faultCodeOf(fault));
    }

    // ---------------------------------------------------------------- 小工具

    private record SoapOrder(List<String> actions) {
    }

    private String soapRaw(String body) {
        String envelope = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
                + "<env:Envelope xmlns:env=\"" + SoapEnvelope.NS_12 + "\"><env:Body>"
                + body + "</env:Body></env:Envelope>";
        HttpHeaders h = new HttpHeaders();
        h.setContentType(MediaType.valueOf(SoapEnvelope.CONTENT_TYPE));
        ResponseEntity<String> r = rest.postForEntity("/api/soap/repair",
                new HttpEntity<>(envelope, h), String.class);
        assertEquals(200, r.getStatusCode().value(),
                "SOAP 的语义是信封到达了，业务失败用 Fault 表达而不是 5xx");
        return r.getBody();
    }

    private List<String> soapIds(String role, String actor) {
        String xml = soapRaw("<ListOrders><Role>" + role + "</Role><Actor>" + actor
                + "</Actor></ListOrders>");
        return texts(xml, "Id");
    }

    private List<String> restIds(String role, String actor) {
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> orders = (List<Map<String, Object>>) rest.getForEntity(
                "/api/orders?role=" + role + "&actor=" + actor, Map.class).getBody().get("orders");
        return orders.stream().map(o -> (String) o.get("id")).toList();
    }

    private SoapOrder soapOrder(String id, String role, String actor) {
        String xml = soapRaw("<GetOrder><Role>" + role + "</Role><Actor>" + actor + "</Actor><Id>"
                + id + "</Id></GetOrder>");
        return new SoapOrder(texts(xml, "Attemptable"));
    }

    @SuppressWarnings("unchecked")
    private List<String> restOrder(String id, String role, String actor) {
        return (List<String>) rest.getForEntity("/api/orders/" + id + "?role=" + role + "&actor="
                + actor, Map.class).getBody().get("attemptable");
    }

    private static List<String> texts(String xml, String localName) {
        try {
            DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
            f.setNamespaceAware(true);
            f.setFeature(javax.xml.XMLConstants.FEATURE_SECURE_PROCESSING, true);
            Document doc = f.newDocumentBuilder()
                    .parse(new ByteArrayInputStream(xml.getBytes(StandardCharsets.UTF_8)));
            NodeList nodes = doc.getElementsByTagNameNS("*", localName);
            List<String> out = new ArrayList<>();
            for (int i = 0; i < nodes.getLength(); i++) {
                out.add(nodes.item(i).getTextContent().trim());
            }
            return out;
        } catch (Exception e) {
            throw new RuntimeException("响应读不回来：" + e.getMessage(), e);
        }
    }

    /** 只取某个 simpleType 里的枚举值，避免把别处的 enumeration 混进来。 */
    private static List<String> enumerations(String wsdl, String typeName) {
        int start = wsdl.indexOf("<xs:simpleType name=\"" + typeName + "\">");
        if (start < 0) {
            return List.of();
        }
        int end = wsdl.indexOf("</xs:simpleType>", start);
        List<String> out = new ArrayList<>();
        java.util.regex.Matcher m = java.util.regex.Pattern
                .compile("<xs:enumeration value=\"([^\"]+)\"/>")
                .matcher(wsdl.substring(start, end));
        while (m.find()) {
            out.add(m.group(1));
        }
        return out;
    }

    private static List<String> sorted(List<String> values) {
        List<String> copy = new ArrayList<>(values);
        java.util.Collections.sort(copy);
        return copy;
    }

    @Test
    void filtersNarrowTheSameWayOnBothInterfaces() {
        String a = create("stu-f1", "A01-220", "NETWORK");
        String b = create("stu-f1", "A01-221", "WATER_ELEC");
        act(a, "submit", "STUDENT", "stu-f1", Map.of());
        act(b, "submit", "STUDENT", "stu-f1", Map.of());

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> restRows = (List<Map<String, Object>>) rest.getForEntity(
                "/api/orders?role=ADMIN&actor=adm-1&category=NETWORK", Map.class)
                .getBody().get("orders");
        List<String> restIds = restRows.stream().map(o -> (String) o.get("id")).toList();
        String envelope = "<ListOrders><Role>ADMIN</Role><Actor>adm-1</Actor><Category>NETWORK"
                + "</Category></ListOrders>";
        assertEquals(restIds, texts(soapRaw(envelope), "Id"), "按分类筛选两边结果必须一致");
        assertTrue(restIds.contains(a));
        assertFalse(restIds.contains(b), "筛选本身也要真的生效");
    }
}

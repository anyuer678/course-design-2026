package course.dormrepair.soap;

import org.junit.jupiter.api.Test;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;

import javax.xml.parsers.DocumentBuilderFactory;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 信封层自己的测试：它不出现在业务判定里，但它决定"客户端收到的到底是结果还是坑"。
 * XXE 那几条是重点——XML 解析器一旦允许 DOCTYPE，报文就不再是数据而是指令。
 */
class SoapEnvelopeTest {

    private static String env12(String body) {
        return "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
                + "<env:Envelope xmlns:env=\"" + SoapEnvelope.NS_12 + "\"><env:Body>"
                + body + "</env:Body></env:Envelope>";
    }

    @Test
    void parsesSoap12And11PrefixesAndNamespaces() throws Exception {
        var req = SoapEnvelope.parse(env12("<ns:ListOrders xmlns:ns=\"" + RepairNamespace.URI
                + "\"><ns:Role>ADMIN</ns:Role><ns:Actor>adm-1</ns:Actor></ns:ListOrders>")
                .getBytes(StandardCharsets.UTF_8));
        assertEquals("ListOrders", req.operation());
        assertEquals("ADMIN", req.required("Role"));
        assertEquals("adm-1", req.required("Actor"));

        // SOAP 1.1 命名空间与前缀也认——interoperability 不靠猜
        String as11 = "<env:Envelope xmlns:env=\"" + SoapEnvelope.NS_11 + "\"><env:Body>"
                + "<ListOrders><Role>WORKER</Role></ListOrders></env:Body></env:Envelope>";
        SoapEnvelope.Request legacy = SoapEnvelope.parse(
                as11.getBytes(StandardCharsets.UTF_8));
        assertEquals("ListOrders", legacy.operation());
        assertEquals("WORKER", legacy.required("Role"));
    }

    @Test
    void missingBodyAndGarbageBecomeFaultsNotExceptions() {
        // 注意括号：`"a" + "b".getBytes()` 里 getBytes 只作用于最后一段字面量，
        // 整个表达式会退化成 String —— 这正是刚才那行编译错误的原因。
        String noBodyEnv = "<env:Envelope xmlns:env=\"" + SoapEnvelope.NS_12 + "\"/>";
        SoapFaultException noBody = assertThrows(SoapFaultException.class,
                () -> SoapEnvelope.parse(noBodyEnv.getBytes(StandardCharsets.UTF_8)));
        assertEquals("VERSION_MISMATCH", noBody.code());

        SoapFaultException junk = assertThrows(SoapFaultException.class,
                () -> SoapEnvelope.parse("这不是 XML".getBytes(StandardCharsets.UTF_8)));
        assertEquals("CLIENT", junk.code(), "解析失败要说清是客户端的锅，不能抛裸异常变成 500");
    }

    @Test
    void refusesDoctypeAndExternalEntities() {
        // 出处：XXE 的经典形态。期望：直接拒绝，且不把被读取文件的内容带到任何输出里。
        String xxe = "<?xml version=\"1.0\"?>"
                + "<!DOCTYPE foo [ <!ENTITY xxe SYSTEM \"file:///C:/Windows/win.ini\"> ]>"
                + "<env:Envelope xmlns:env=\"" + SoapEnvelope.NS_12 + "\"><env:Body>"
                + "<ListOrders><Role>&xxe;</Role><Actor>a</Actor></ListOrders>"
                + "</env:Body></env:Envelope>";
        SoapFaultException boom = assertThrows(SoapFaultException.class,
                () -> SoapEnvelope.parse(xxe.getBytes(StandardCharsets.UTF_8)));
        assertEquals("CLIENT", boom.code(), "DOCTYPE 必须被显式挡掉");
        assertTrue(boom.getMessage().contains("DOCTYPE"), boom.getMessage());
        // 兜底第二层：真有实体请求时 entityResolver 会抛，绝不去读文件系统
        assertFalse(boom.getMessage().contains("win.ini"), boom.getMessage());
    }

    @Test
    void entityInsidePayloadWithoutDoctypeStillCannotResolve() {
        // 没有 DOCTYPE 就没有已声明实体可用；这里验的是"实体引用不会静默变成别处的内容"
        String withRef = "<env:Envelope xmlns:env=\"" + SoapEnvelope.NS_12 + "\"><env:Body>"
                + "<GetOrder><Role>&xxe;</Role><Actor>a</Actor></GetOrder></env:Body></env:Envelope>";
        SoapFaultException boom = assertThrows(SoapFaultException.class,
                () -> SoapEnvelope.parse(withRef.getBytes(StandardCharsets.UTF_8)));
        assertEquals("CLIENT", boom.code(), boom.getMessage());
    }

    @Test
    void escapingSurvivesRoundTripForChineseAndMarkup() {
        String payload = SoapEnvelope.response("GetOrder", List.of(
                SoapEnvelope.Item.of("Description", "漏水 <script>alert(1)</script> & 中文 ✓")));
        assertTrue(payload.contains("&lt;script&gt;"), payload);
        assertFalse(payload.contains("<script>"), "响应不许把用户文本当标签吐回去");

        String xml = SoapEnvelope.response("ListOrders", List.of(
                SoapEnvelope.Item.of("Count", "2"),
                SoapEnvelope.Item.of("Order", List.of(
                        SoapEnvelope.Item.of("Id", "R001"),
                        SoapEnvelope.Item.of("Room", "A01-101"))),
                SoapEnvelope.Item.of("Order", List.of(SoapEnvelope.Item.of("Id", "R002")))));
        List<String> ids = childTexts(xml, "Id");
        assertEquals(List.of("R001", "R002"), ids, "嵌套元素要能被正常读回，否则客户端只能靠字符串找茬");
        assertEquals("2", childTexts(xml, "Count").get(0));
    }

    @Test
    void faultCarriesTheDomainErrorCodeNotASoapCategory() {
        String fault = SoapEnvelope.fault("ACCEPTANCE_NOT_MATURE", "停留未满宽限期（BR-10）", true);
        assertTrue(fault.contains("env:Sender"), "SOAP 1.2 的 mcode 表示谁错了");
        assertTrue(fault.contains("ns:ACCEPTANCE_NOT_MATURE"), "业务码放 Subcode：" + fault);
        // 读回来必须是**裸码**，与 REST 的 `error` 字段逐字可比
        assertEquals("ACCEPTANCE_NOT_MATURE", SoapEnvelope.faultCodeOf(fault));
        assertEquals("", SoapEnvelope.faultCodeOf(
                SoapEnvelope.fault("CLIENT", "格式错", true).replace("Subcode", "Nope")),
                "没有 Subcode 时返回空串，而不是抛异常或猜一个");
    }

    /** 用真的 DOM 解析器读回去——这比正则更接近客户端的视角。 */
    private static List<String> childTexts(String xml, String localName) {
        try {
            DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
            f.setNamespaceAware(true);
            Document doc = f.newDocumentBuilder()
                    .parse(new ByteArrayInputStream(xml.getBytes(StandardCharsets.UTF_8)));
            List<String> out = new ArrayList<>();
            NodeList all = doc.getElementsByTagNameNS("*", localName);
            for (int i = 0; i < all.getLength(); i++) {
                Element el = (Element) all.item(i);
                out.add(el.getTextContent());
            }
            return out;
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }
}

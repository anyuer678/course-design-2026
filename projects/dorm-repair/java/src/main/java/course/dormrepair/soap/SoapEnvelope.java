package course.dormrepair.soap;

import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;
import org.xml.sax.SAXException;

import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.parsers.ParserConfigurationException;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * SOAP 信封的读与写（B19）。**只用 JDK 自带的 `java.xml`**：
 * 本机 `~/.m2` 没有 Spring WS / SAAJ / Axis / gRPC，而 PLAN 第 8 节要求下载先征得同意，
 * 所以这一层是手写的——好处是"两种接口、一份规则"这件事没有任何黑盒可藏。
 *
 * 安全边界写死在这里，不提供"退一步宽松解析"的选项：
 * 禁用 DOCTYPE（挡住 XXE 与 entity 放大）。工厂若不支持该特性就**抛错**，
 * 而不是换成一个不设防的解析器继续跑。
 */
public final class SoapEnvelope {

    public static final String NS_12 = "http://www.w3.org/2003/05/soap-envelope";
    public static final String NS_11 = "http://schemas.xmlsoap.org/soap/envelope/";
    public static final String CONTENT_TYPE = "application/soap+xml; charset=utf-8";

    /** 解析出来的请求：操作名 + 该操作下所有直接子元素的文本（按名字首次出现取值）。 */
    public record Request(String operation, Map<String, String> elements) {

        public String text(String name, String fallback) {
            String value = elements.get(name);
            return value == null || value.isBlank() ? fallback : value.trim();
        }

        public String required(String name) {
            return elements.getOrDefault(name, "").trim();
        }
    }

    private SoapEnvelope() {
    }

    public static Request parse(byte[] payload) throws SoapFaultException {
        Document doc = parseXml(payload);
        Element body = firstChild(doc.getDocumentElement(), "Body");
        if (body == null) {
            throw new SoapFaultException("VERSION_MISMATCH", "信封里没有 soap:Body");
        }
        Element operation = firstElementChild(body);
        if (operation == null) {
            throw new SoapFaultException("CLIENT", "Body 里没有任何操作元素");
        }
        Map<String, String> elements = new LinkedHashMap<>();
        NodeList kids = operation.getChildNodes();
        for (int i = 0; i < kids.getLength(); i++) {
            Node node = kids.item(i);
            if (node.getNodeType() == Node.ELEMENT_NODE) {
                // 同名元素只保留第一个；重复参数不是本接口的表达力，别偷偷合并
                elements.putIfAbsent(node.getLocalName() != null ? node.getLocalName()
                        : node.getNodeName(), node.getTextContent());
            }
        }
        String name = operation.getLocalName() != null ? operation.getLocalName()
                : operation.getNodeName();
        return new Request(name, elements);
    }

    private static Document parseXml(byte[] payload) throws SoapFaultException {
        // 实测教训：`http://apache.org/xml/features/disallow-doctype-declaration` 是 Xerces 专有的，
        // JDK 自带解析器不认这个名字（第一版我照抄了网上那套配置，结果每次请求都走"失败关闭"分支，
        // 防护实际上从未生效，只是恰好把请求都拒了）。所以这里显式挡在解析之前。
        String head = new String(payload, 0, Math.min(payload.length, 4096), StandardCharsets.UTF_8)
                .toLowerCase();
        if (head.contains("<!doctype") || head.contains("<!entity")) {
            throw new SoapFaultException("CLIENT",
                    "信封里出现 DOCTYPE/ENTITY：本服务不接受（XXE 与实体放大攻击面）");
        }
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        factory.setNamespaceAware(true);              // 不然认不出 soap: 前缀背后的命名空间
        try {
            factory.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
            factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, "");   // JDK 支持这个属性
        } catch (ParserConfigurationException | IllegalArgumentException notSupported) {
            throw new SoapFaultException("INTERNAL", "XML 解析器无法安全配置，拒绝解析："
                    + notSupported.getMessage());
        }
        try {
            DocumentBuilder builder = factory.newDocumentBuilder();
            // 兜底：真有实体解析请求时，宁可报错也不去读任何东西
            builder.setEntityResolver((publicId, systemId) -> {
                throw new SAXException("禁止外部实体（XXE）：" + systemId);
            });
            return builder.parse(new ByteArrayInputStream(payload));
        } catch (SAXException e) {
            throw new SoapFaultException("CLIENT", "信封不是合法 XML：" + e.getMessage());
        } catch (IOException e) {
            throw new SoapFaultException("CLIENT", "读取信封失败：" + e.getMessage());
        } catch (ParserConfigurationException e) {
            throw new SoapFaultException("INTERNAL", "解析器不可用：" + e.getMessage());
        }
    }

    /**
     * 从故障 XML 里取回**业务错误码**。
     * SOAP 1.2 的 Subcode Value 是个 QName（`ns:ROLE_NOT_ALLOWED`），
     * 而 REST 给的是裸码；不剥前缀的话"双接口同一码"就只能靠字符串 indexOf 自证。
     */
    public static String faultCodeOf(String faultXml) {
        try {
            DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
            f.setNamespaceAware(true);
            f.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
            Document doc = f.newDocumentBuilder()
                    .parse(new ByteArrayInputStream(faultXml.getBytes(StandardCharsets.UTF_8)));
            NodeList sub = doc.getElementsByTagNameNS(NS_12, "Subcode");
            if (sub.getLength() == 0) {
                return "";
            }
            NodeList values = ((Element) sub.item(0)).getElementsByTagNameNS(NS_12, "Value");
            if (values.getLength() == 0) {
                return "";
            }
            String qname = values.item(0).getTextContent().trim();
            int colon = qname.indexOf(':');
            return colon < 0 ? qname : qname.substring(colon + 1);
        } catch (ParserConfigurationException | SAXException | IOException e) {
            throw new IllegalStateException("自家生成的故障信封读不回来：" + e.getMessage(), e);
        }
    }

    /** 成功响应：`Env:Envelope/Body/<Operation>Response` 里塞若干元素。 */
    public static String response(String operation, List<Item> children) {
        StringBuilder sb = new StringBuilder();
        sb.append("<?xml version=\"1.0\" encoding=\"UTF-8\"?>")
                .append("<env:Envelope xmlns:env=\"").append(NS_12).append("\">")
                .append("<env:Body><ns:").append(operation).append("Response xmlns:ns=\"")
                .append(RepairNamespace.URI).append("\">");
        for (Item child : children) {
            sb.append(child.toXml());
        }
        sb.append("</ns:").append(operation).append("Response></env:Body></env:Envelope>");
        return sb.toString();
    }

    /**
     * 故障。`code` 用**领域里那套错误码**（ROLE_NOT_ALLOWED / OWNER / ACCEPTANCE_NOT_MATURE…），
     * 不是 SOAP 自己的分类——这样"两种接口一份规则"才真的能在测试里逐字比对。
     * SOAP 1.2 的 mcode 只表示"发送方错还是接收方错"，放在 sub_code 之外的属性里。
     */
    public static String fault(String code, String reason, boolean senderSide) {
        String mcode = senderSide ? "env:Sender" : "env:Receiver";
        return "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
                + "<env:Envelope xmlns:env=\"" + NS_12 + "\"><env:Body><env:Fault>"
                + "<env:Code><env:Value>" + mcode + "</env:Value>"
                + "<env:Subcode><env:Value xmlns:ns=\"" + RepairNamespace.URI + "\">ns:"
                + escape(code) + "</env:Value></env:Subcode></env:Code>"
                + "<env:Reason><env:Text xml:lang=\"zh\">" + escape(reason) + "</env:Text>"
                + "</env:Reason></env:Fault></env:Body></env:Envelope>";
    }

    public static String escape(String raw) {
        if (raw == null) {
            return "";
        }
        return raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("\"", "&quot;");
    }

    private static Element firstChild(Element parent, String localName) {
        if (parent == null) {
            return null;
        }
        NodeList kids = parent.getChildNodes();
        for (int i = 0; i < kids.getLength(); i++) {
            Node node = kids.item(i);
            if (node.getNodeType() == Node.ELEMENT_NODE && localName.equals(localNameOf(node))) {
                return (Element) node;
            }
        }
        return null;
    }

    private static Element firstElementChild(Element parent) {
        NodeList kids = parent.getChildNodes();
        for (int i = 0; i < kids.getLength(); i++) {
            if (kids.item(i).getNodeType() == Node.ELEMENT_NODE) {
                return (Element) kids.item(i);
            }
        }
        return null;
    }

    private static String localNameOf(Node node) {
        return node.getLocalName() != null ? node.getLocalName() : node.getNodeName();
    }

    /** 响应里的一个元素，名字 + 文本，或名字 + 子元素。 */
    public record Item(String name, String text, List<Item> children) {

        public static Item of(String name, String text) {
            return new Item(name, text, List.of());
        }

        public static Item of(String name, List<Item> children) {
            return new Item(name, null, List.copyOf(children));
        }

        public String toXml() {
            if (children.isEmpty()) {
                return "<" + name + ">" + escape(text == null ? "" : text) + "</" + name + ">";
            }
            StringBuilder sb = new StringBuilder("<").append(name).append(">");
            List<String> parts = new ArrayList<>();
            for (Item child : children) {
                parts.add(child.toXml());
            }
            sb.append(String.join("", parts)).append("</").append(name).append(">");
            return sb.toString();
        }
    }
}

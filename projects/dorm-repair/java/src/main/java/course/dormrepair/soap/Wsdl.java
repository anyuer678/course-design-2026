package course.dormrepair.soap;

import course.dormrepair.contract.WorkflowContract;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * WSDL 2.0 描述，**由契约生成**（ADR-03 的延伸）：
 * 状态、动作、错误码、可见性代码都从 `workflow.json` 读，不在这个文件里手抄第二份。
 *
 * 为什么值得生成而不只是写一份静态文档：描述文件一旦与契约分叉，客户端就会按一个
 * 服务端已经不接受的枚举值发消息——而那不会有任何报错，只会变成"莫名其妙的拒绝"。
 * `WsdlTest` 逐字比对这里的枚举集合与契约集合。
 */
public final class Wsdl {

    private Wsdl() {
    }

    public static String of(WorkflowContract contract, Map<String, List<String>> operations) {
        List<String> parts = new ArrayList<>();
        parts.add("<?xml version=\"1.0\" encoding=\"UTF-8\"?>");
        parts.add("<description xmlns=\"http://www.w3.org/ns/wsdl\" "
                + "xmlns:tns=\"" + RepairNamespace.URI + "\" "
                + "xmlns:xs=\"http://www.w3.org/2001/XMLSchema\" "
                + "xmlns:soap=\"http://www.w3.org/ns/wsdl/soap\""
                + " targetNamespace=\"" + RepairNamespace.URI + "\">");
        parts.add("<documentation>报修系统查询用例（UC-05）的 SOAP 形态。"
                + "状态、动作、错误码均来自 contracts/workflow.json（schema v"
                + contract.schemaVersion() + "），不是手写清单。</documentation>");
        parts.add("<types><xs:schema><xs:annotation><xs:documentation source="
                + "\"https://dorm-repair.local/contract/workflow.json\"/></xs:annotation>");
        parts.add(enumeration("State", contract.states()));
        parts.add(enumeration("Action", contract.actions()));
        parts.add(enumeration("Role", contract.roles()));
        parts.add(enumeration("Category", contract.categories()));
        parts.add(enumeration("Priority", contract.priorities()));
        parts.add(enumeration("VisibilityCode", new ArrayList<>(contract.visibility().values())));
        // 错误码来自契约的前置条件 + 本服务会透出的判定码；两边同源才不会各说一遍
        parts.add(enumeration("FaultCode", faultCodes(contract)));
        parts.add("</xs:schema></types>");

        for (Map.Entry<String, List<String>> entry : new java.util.TreeMap<>(operations).entrySet()) {
            String op = entry.getKey();
            parts.add("<message name=\"" + op + "Request\">");
            for (String part : entry.getValue()) {
                parts.add("<part name=\"" + part + "\" type=\"" + typeOf(part, contract) + "\"/>");
            }
            parts.add("</message>");
            parts.add("<message name=\"" + op + "Response\">"
                    + "<part name=\"Count\" type=\"xs:integer\"/>"
                    + "<part name=\"Order\" type=\"tns:OrderType\"/></message>");
        }
        parts.add("<interface name=\"RepairQueryInterface\">");
        parts.add("<documentation>只做查询。任何写操作都只存在于 REST 一侧的同一份判定上，"
                + "本接口不重复实现规则。</documentation>");
        for (String op : new java.util.TreeMap<>(operations).keySet()) {
            parts.add("<operation name=\"" + op + "\" pattern=\"http://www.w3.org/ns/wsdl/in-out\""
                    + " style=\"http://www.w3.org/ns/wsdl/style/iri/http-slash\""
                    + " inputMessage=\"tns:" + op + "Request\" outputMessage=\"tns:" + op + "Response\">"
                    + "<fault name=\"Fault\" element=\"soap12:Fault\"/></operation>");
        }
        parts.add("</interface>");
        parts.add("<binding name=\"RepairSoapBinding\" interface=\"tns:RepairQueryInterface\""
                + " type=\"http://www.w3.org/ns/wsdl/binding/soap12\">"
                + "<property name=\"httpBindingLocation\" value=\"/api/soap/repair\"/></binding>");
        parts.add("<service name=\"RepairQueryService\" interface=\"tns:RepairQueryInterface\">"
                + "<endpoint binding=\"tns:RepairSoapBinding\""
                + " address=\"/api/soap/repair\"/></service>");
        parts.add("</description>");
        return String.join("\n", parts);
    }

    private static String enumeration(String name, List<String> values) {
        StringBuilder sb = new StringBuilder("<xs:simpleType name=\"").append(name).append("Type\">")
                .append("<xs:restriction base=\"xs:string\"><xs:enumeration value=\"__NONE__\"/></xs:restriction>")
                .append("</xs:simpleType>");
        if (values == null || values.isEmpty()) {
            return sb.toString();
        }
        StringBuilder e = new StringBuilder("<xs:simpleType name=\"").append(name).append("Type\">")
                .append("<xs:restriction base=\"xs:string\">");
        for (String value : values) {
            e.append("<xs:enumeration value=\"").append(SoapEnvelope.escape(value)).append("\"/>");
        }
        return e.append("</xs:restriction></xs:simpleType>").toString();
    }

    private static List<String> faultCodes(WorkflowContract contract) {
        List<String> codes = new ArrayList<>();
        codes.add("NO_SUCH_TRANSITION");
        codes.add("ROLE_NOT_ALLOWED");
        codes.add("BAD_IDENTITY");
        codes.add("NOT_FOUND");
        codes.add("INVALID_FIELDS");
        codes.add("CONCURRENT_UPDATE");
        codes.add("CLIENT");
        codes.add("INTERNAL");
        // 每个前置条件都可能变成一个拒绝码，所以它们也必须来自契约
        codes.addAll(new java.util.TreeSet<>(contract.preconditions()));
        codes.sort(String::compareTo);
        return codes;
    }

    private static String typeOf(String part, WorkflowContract contract) {
        return switch (part) {
            case "Role" -> "tns:RoleType";
            case "State" -> "tns:StateType";
            case "Category" -> "tns:CategoryType";
            case "Priority" -> "tns:PriorityType";
            case "Overdue" -> "xs:boolean";
            default -> "xs:string";
        };
    }
}

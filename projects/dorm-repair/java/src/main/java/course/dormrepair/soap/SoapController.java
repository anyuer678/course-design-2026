package course.dormrepair.soap;

import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * SOAP 端点：与 REST 并列的第二种接口形态（B19）。
 *
 * 它**只转发**：解析信封 → 调 `SoapQueryService`（那里再调应用服务与领域）→ 序列化信封。
 * HTTP 状态码在这里几乎恒为 200，因为 SOAP 的语义是"信封到达了，结果可能是 Fault"——
 * 这一点与 REST 用状态码表达拒绝正好相反，也是本轮为什么要用**错误码**而不是状态码来做双接口对拍。
 */
@RestController
@RequestMapping("/api/soap")
public class SoapController {

    private static final MediaType SOAP_XML = MediaType.valueOf("application/soap+xml;charset=UTF-8");
    private static final String XML = "text/xml;charset=UTF-8";

    private final SoapQueryService queries;

    public SoapController(SoapQueryService queries) {
        this.queries = queries;
    }

    @PostMapping(value = "/repair", consumes = {MediaType.APPLICATION_XML_VALUE,
            "application/soap+xml", MediaType.TEXT_XML_VALUE},
            produces = XML)
    public ResponseEntity<String> repair(@RequestBody byte[] envelope) {
        return ResponseEntity.ok()
                .contentType(SOAP_XML)
                .body(queries.handle(envelope));
    }

    /** WSDL 由契约现算，不是放在 resources 里的手写文档。 */
    @GetMapping(value = "/repair", params = "wsdl", produces = XML)
    public ResponseEntity<String> wsdl() {
        return ResponseEntity.ok().contentType(MediaType.valueOf(XML)).body(queries.wsdl());
    }
}

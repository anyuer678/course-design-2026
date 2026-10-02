package course.dormrepair.soap;

/** 信封层的问题（不是业务判定）。业务错误直接复用领域抛出的错误码，不在这层重新分类。 */
public class SoapFaultException extends Exception {
    private final String code;

    public SoapFaultException(String code, String reason) {
        super(reason);
        this.code = code;
    }

    public String code() {
        return code;
    }
}

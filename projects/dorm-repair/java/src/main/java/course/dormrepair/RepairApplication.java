package course.dormrepair;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/** B18 平台层入口。存储是 H2（文件库或内存库，由 spring.datasource.url 决定）。 */
@SpringBootApplication
public class RepairApplication {

    public static void main(String[] args) {
        SpringApplication.run(RepairApplication.class, args);
    }
}

package course.dormrepair.infra;

import course.dormrepair.domain.TimeSource;

/** 真实时钟。整个系统里只有这一处读 `System.currentTimeMillis()`（NFR-05）。 */
public class SystemTimeSource implements TimeSource {

    @Override
    public double now() {
        return System.currentTimeMillis() / 1000.0;
    }
}

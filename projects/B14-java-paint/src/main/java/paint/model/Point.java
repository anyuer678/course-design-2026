package paint.model;

/**
 * 画布上的整数坐标点。不可变：形状也全部不可变，撤销才不会有"半个对象被两条命令共享"的坑。
 */
public record Point(int x, int y) {

    /** 到线段所在直线的距离用的近似度量：整数平方距离，够命中判断用，不开方。 */
    public long squaredDistanceTo(Point other) {
        long dx = x - other.x;
        long dy = y - other.y;
        return dx * dx + dy * dy;
    }

    /** 点到线段 ab 的平方距离。投影参数用整数夹紧到 [0,1]，退化线段（a==b）直接按点算。 */
    public long squaredDistanceToSegment(Point a, Point b) {
        long vx = b.x - a.x;
        long vy = b.y - a.y;
        long wx = x - a.x;
        long wy = y - a.y;
        long lenSq = vx * vx + vy * vy;
        if (lenSq == 0) {
            return wx * wx + wy * wy;
        }
        long numerator = wx * vx + wy * vy;
        long clamped = Math.max(0L, Math.min(lenSq, numerator));
        // 用定点数避免浮点：closest = a + v * clamped / lenSq
        long cx = a.x + vx * clamped / lenSq;
        long cy = a.y + vy * clamped / lenSq;
        long dx = x - cx;
        long dy = y - cy;
        return dx * dx + dy * dy;
    }
}

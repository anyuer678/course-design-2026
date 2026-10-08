package paint.ui;

/** 工具：画笔自由手绘 + 三种画 shapes 的工具 + 一个选择工具。加一种图形只要在这里加一项、工厂里加一个分支。 */
public enum Tool {
    SELECT("选择/移动"), PENCIL("画笔"), LINE("线段"), RECT("矩形"), ELLIPSE("椭圆");

    private final String label;

    Tool(String label) {
        this.label = label;
    }

    public String label() {
        return label;
    }

    public boolean isDrawingTool() {
        return this != SELECT;
    }
}

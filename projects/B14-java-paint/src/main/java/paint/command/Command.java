package paint.command;

/**
 * 一条可撤销的编辑操作（命令模式）。
 *
 * <p>这里用它不是为了"模式"本身：画图的撤销/重做必须把"做了什么"变成对象，
 * 才能事后倒着执行。没有这层，就只能给每个操作写一份反向代码并手工保持同步——
 * 那正是撤销功能最容易出错的地方。
 *
 * <p>约定：{@link #execute()} 与 {@link #undo()} 都必须只依赖文档的当前状态，
 * 不许在构造时就 assuming 位置（插入后的真实下标要由 execute 回填）。
 */
public interface Command {

    /** 正向执行。第一次由 {@link CommandHistory#run} 调用，重做时也由它调用。 */
    void execute();

    /** 反向执行，必须把文档恢复到 execute 之前那一刻。 */
    void undo();

    /** 给状态栏和"撤销：xxx"菜单用的中文描述。 */
    String describe();
}

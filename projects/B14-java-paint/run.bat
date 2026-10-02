@echo off
rem 源码是 UTF-8，中文 Windows 默认代码页 936 会把提示解析成乱码
chcp 65001 >nul
rem B14-java-paint 一键脚本：编译 → 无头自测 → 离屏演示 → 打开真窗口
rem 只跑到离屏那一步（CI、或者不想弹窗口）：run.bat no-gui
setlocal
cd /d %~dp0
set JAVA_FLAGS=-Dfile.encoding=UTF-8 -Dstdout.encoding=UTF-8

where javac >nul 2>nul || (echo [!] 找不到 javac，请先装 JDK 17 或更高 & exit /b 1)
if exist out rmdir /s /q out
mkdir out

echo [1/4] 编译
echo       本次用的编译器：
javac -version 2>&1
rem 本机同时装了 JDK 21（在 PATH）和 JDK 17（JAVA_HOME 指向它）：
rem 不锁 --release 17 的话，代码可能用到只在新版本才有的 API，换台机器就编不过。
dir /s /b src\main\java\*.java > out\sources-main.txt
javac --release 17 -encoding UTF-8 -d out\classes @out\sources-main.txt || exit /b 1
dir /s /b src\test\java\*.java > out\sources-test.txt
javac --release 17 -encoding UTF-8 -cp out\classes -d out\test-classes @out\sources-test.txt || exit /b 1
echo       编译通过（out\classes 与 out\test-classes）

echo.
echo [2/4] 无头自测（不开任何窗口，全程 -Djava.awt.headless=true）...
java -Djava.awt.headless=true %JAVA_FLAGS% -cp "out\classes;out\test-classes" paint.PaintTests || exit /b 1

echo.
echo [3/4] 离屏演示：命令层画三个形状 -> 撤销 -> 重做 -> 数像素 -> PNG 写进临时目录...
java -Djava.awt.headless=true %JAVA_FLAGS% -cp out\classes paint.App --demo || exit /b 1

if /i "%~1"=="no-gui" (
    echo.
    echo [4/4] 已按 no-gui 跳过打开窗口。要人工验证就直接跑：run.bat
    echo.
    echo 全部完成。测试与离屏演示没在项目目录留下多余文件，保存或导出后 data 目录里才会有 .pad 与 .png
    exit /b 0
)

echo.
echo [4/4] 打开画图窗口。请依次试：
echo       1 选"矩形"，在画布上按住拖动，松手 - 出现一个矩形
echo       2 选"椭圆"再画一个，然后按 Ctrl+Z 撤销 - 椭圆消失
echo       3 按 Ctrl+Y 重做 - 椭圆回来
echo       4 选"选择/移动"，点一个形状再拖动它；按 Delete 删掉选中的
echo       5 保存为 .pad，点"新建"清空，再"打开"把刚才那份读回来
echo       6 导出 PNG 到 data 目录（这一步的效果我只能靠你看，我不会替你勾）
echo       关闭窗口即结束；有未保存修改时会先问一句。
start /wait "" java %JAVA_FLAGS% -cp out\classes paint.App

echo.
echo 全部完成。保存的文档与导出的图片都在 data 目录。
endlocal

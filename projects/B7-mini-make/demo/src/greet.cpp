// demo/src/greet.cpp —— 供 mini-make 增量构建演示用的小程序
#include <cstdio>

int main() {
    for (int i = 0; i < 3; ++i)
        std::printf("hello from mini-make #%d\n", i + 1);
    return 0;
}

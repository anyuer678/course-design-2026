// tools/export_trace.cpp —— B33 的导出器：用 B2 的结构库跑固定场景，吐"操作记录"JSON
//
// 分工（复用纪律）：B2 提供只读 trace 观察口（事件与实现天然同步）；
// 本工具负责"跑什么场景 + 导成什么格式"（显示格式是 B33 的事）。
// 场景故意小而立得住：8 个数的堆排序、7 个结点的图（含两个连通分量）。
//
// 输出（写到 argv[1] 目录下）：
//   sort.json  堆排序：input + 逐步 steps（swap/build/pop；state = 已排序前缀 + 堆区，
//              out = 前缀长度——回放器据此把一维数组分成"绿色已排区"和"蓝色堆区"）
//   bfs.json   从结点 0 的 BFS：visit 步（a=结点, b=距离, state=队列内容）
//   dfs.json   从结点 0 的 DFS：visit 步（a=结点, state=栈内容）
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#include "ds/graph.hpp"
#include "ds/heap.hpp"
#include "ds/trace.hpp"

static void write_long_array(FILE* f, const std::vector<int>& v) {
    std::fprintf(f, "[");
    for (std::size_t i = 0; i < v.size(); ++i) {
        std::fprintf(f, "%s%d", i ? "," : "", v[i]);
    }
    std::fprintf(f, "]");
}

static void write_state(FILE* f, const std::vector<long long>& s) {
    std::fprintf(f, "[");
    for (std::size_t i = 0; i < s.size(); ++i) {
        std::fprintf(f, "%s%lld", i ? "," : "", s[i]);
    }
    std::fprintf(f, "]");
}

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "用法：export_trace <输出目录>\n");
        return 2;
    }
    const std::string dir = argv[1];

    // ---------------------------------------------------------------- 堆排序
    std::vector<int> input = {5, 1, 4, 2, 8, 3, 7, 6};
    std::vector<int> v = input;
    ds::Heap<int> heap;
    ds::Tracer tracer;
    tracer.enable();
    heap.set_tracer(&tracer);

    heap.build(v);
    const std::size_t n = v.size();
    for (std::size_t i = 0; i < n; ++i) {
        v[i] = heap.top();
        heap.pop();
    }

    {
        FILE* f = std::fopen((dir + "/sort.json").c_str(), "w");
        if (!f) { std::perror("sort.json"); return 1; }
        std::fprintf(f, "{\"type\":\"sort\",\"algorithm\":\"heap_sort(min-heap)\",\"input\":");
        write_long_array(f, input);
        std::fprintf(f, ",\"steps\":[");
        std::size_t pops = 0;
        for (std::size_t e = 0; e < tracer.events.size(); ++e) {
            const ds::TraceEvent& ev = tracer.events[e];
            // 前缀口径：pop 事件完成时，已排序前缀**包含刚取出的那个值**；
            // 其余事件（build/交换）的前缀 = 已完成的取出次数
            std::size_t prefix = pops + (ev.op == "pop" ? 1 : 0);
            if (ev.op == "pop") ++pops;
            std::fprintf(f, "%s{\"op\":\"%s\",\"a\":%lld,\"b\":%lld,\"out\":%zu,\"state\":[",
                         e ? "," : "", ev.op.c_str(), ev.a, ev.b, prefix);
            for (std::size_t i = 0; i < prefix; ++i) std::fprintf(f, "%s%d", i ? "," : "", v[i]);
            for (std::size_t i = 0; i < ev.state.size(); ++i) {
                std::fprintf(f, "%s%lld", (i || prefix) ? "," : "", ev.state[i]);
            }
            std::fprintf(f, "]}");
        }
        std::fprintf(f, "]}\n");
        std::fclose(f);
    }

    // ---------------------------------------------------------------- 图遍历
    ds::Graph g(7);
    const int edge_list[][2] = {{0, 1}, {0, 2}, {1, 3}, {2, 4}, {2, 5}, {5, 6}};
    for (const auto& e : edge_list) g.add_edge(e[0], e[1]);

    for (const std::string algo : {"bfs", "dfs"}) {
        ds::Tracer gt;
        gt.enable();
        g.set_tracer(&gt);
        std::vector<int> dist, order;
        if (algo == "bfs") g.bfs(0, dist, order);
        else g.dfs(0, order);
        g.set_tracer(nullptr);

        FILE* f = std::fopen((dir + "/" + algo + ".json").c_str(), "w");
        if (!f) { std::perror(algo.c_str()); return 1; }
        std::fprintf(f, "{\"type\":\"graph\",\"algorithm\":\"%s\",\"from\":0,\"nodes\":7,\"edges\":[",
                     algo.c_str());
        for (std::size_t i = 0; i < sizeof(edge_list) / sizeof(edge_list[0]); ++i) {
            std::fprintf(f, "%s[%d,%d]", i ? "," : "", edge_list[i][0], edge_list[i][1]);
        }
        std::fprintf(f, "],\"steps\":[");
        for (std::size_t e = 0; e < gt.events.size(); ++e) {
            const ds::TraceEvent& ev = gt.events[e];
            std::fprintf(f, "%s{\"op\":\"%s\",\"a\":%lld,\"b\":%lld,\"state\":",
                         e ? "," : "", ev.op.c_str(), ev.a, ev.b);
            write_state(f, ev.state);
            std::fprintf(f, "}");
        }
        std::fprintf(f, "]}\n");
        std::fclose(f);
    }

    std::printf("导出完成：sort.json（%zu 事件）、bfs.json、dfs.json\n", tracer.events.size());
    return 0;
}

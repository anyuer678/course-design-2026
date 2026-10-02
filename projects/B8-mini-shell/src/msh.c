/* src/msh.c —— B8 教学 mini-shell（POSIX）
 *
 * 课程要点（开源操作系统 / 进程与 shell）：
 *   - shell 的本质是一个**循环**：读一行 → 解析 → fork/exec → 回收 → 再来。
 *     "minishell 为什么必须有 fork"：内建命令（cd）要改的是**shell 自己**的进程状态，
 *     外部命令要的是**另一个进程**——这一条把两类命令的分工解释清楚；
 *   - 管道 = N 个进程 + N-1 根 pipe：每根管子有写端（前一个命令的 stdout）与读端
 *     （后一个命令的 stdin），父进程 **必须把两个端都按需关掉**，不然读端永远等不到 EOF；
 *   - 重定向是 dup2 的艺术：`< f` 把 fd 0 换成文件、`> f` 换 fd 1、"`>>`" 只是换个
 *     open 标 志（O_TRUNC vs O_APPEND）——管道与重定向撞车时，**后处理的赢**（本实现
 *     先接管道再应用重定向，和真实 shell 的次序一致）；
 *   - 子进程回收：每个 fork 出来的进程都要 waitpid（按序收全部，不止最后一个）；
 *     不回收就是僵尸——测试里的"0 僵尸"是去 /proc 里当面数出来的；
 *   - 读命令行用**逐字节 read**而不是 fgets：stdio 会预读缓冲，把本应留给
 *     `cat` 这类子进程的 stdin 先吞掉（这条坑写在这里，测试有 `cat` 继承 stdin 的用例）。
 *
 * 红线（范围声明）：不做变量展开、通配符、作业控制、信号处理教程级内容（Ctrl-C
 * 只做最小正确行为：shell 忽略 SIGINT、子进程恢复默认）；`#` 注释与引号是最小支持集。
 */
#define _POSIX_C_SOURCE 200809L

#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

#define MSH_MAX_TOKENS 128
#define MSH_MAX_CMDS 16
#define MSH_LINE 4096

typedef struct {
    char *argv[MSH_MAX_TOKENS];
    int argc;
    const char *in_path;      /* < file   */
    const char *out_path;     /* > file / >> file */
    int out_append;
} Command;

/* ---------------------------------------------------------------- 词法 */

static char *g_tokens[MSH_MAX_TOKENS];
static int g_ntokens = 0;

static void tokens_free(void) {
    for (int i = 0; i < g_ntokens; ++i) free(g_tokens[i]);
    g_ntokens = 0;
}

static int token_add(const char *s) {
    if (g_ntokens >= MSH_MAX_TOKENS) {
        fprintf(stderr, "msh: 命令行记号太多（上限 %d）\n", MSH_MAX_TOKENS);
        return -1;
    }
    g_tokens[g_ntokens] = strdup(s);
    if (!g_tokens[g_ntokens]) {
        fprintf(stderr, "msh: 内存不足\n");
        return -1;
    }
    ++g_ntokens;
    return 0;
}

/* 引号内空白保留；双引号里支持 \" 与 \\；运算符 | < > >> 独立成 token */
static int lex(char *line) {
    char *p = line;
    char word[MSH_LINE];
    while (*p) {
        while (*p == ' ' || *p == '\t') ++p;
        if (!*p) break;
        if (*p == '|' || *p == '<') {
            char op[2] = {*p, '\0'};
            if (token_add(op) < 0) return -1;
            ++p;
            continue;
        }
        if (*p == '>') {
            if (p[1] == '>') {
                if (token_add(">>") < 0) return -1;
                p += 2;
            } else {
                if (token_add(">") < 0) return -1;
                ++p;
            }
            continue;
        }
        size_t w = 0;
        while (*p && !strchr(" \t|<>", *p)) {
            if (*p == '\'' || *p == '"') {
                char quote = *p++;
                while (*p && *p != quote) {
                    if (quote == '"' && *p == '\\' && (p[1] == '"' || p[1] == '\\')) ++p;
                    if (w + 1 >= sizeof word) {
                        fprintf(stderr, "msh: 单词太长\n");
                        return -1;
                    }
                    word[w++] = *p++;
                }
                if (*p != quote) {
                    fprintf(stderr, "msh: 引号没有闭合\n");
                    return -1;
                }
                ++p;
            } else {
                if (w + 1 >= sizeof word) {
                    fprintf(stderr, "msh: 单词太长\n");
                    return -1;
                }
                word[w++] = *p++;
            }
        }
        word[w] = '\0';
        if (token_add(word) < 0) return -1;
    }
    return 0;
}

/* ---------------------------------------------------------------- 语法（token → 管道） */

static Command g_cmds[MSH_MAX_CMDS];
static int g_ncmds = 0;

/* 返回 0 成功；-1 时把原因写进 msg（调用方打印） */
static int build_pipeline(char *msg, size_t msg_size) {
    g_ncmds = 0;
    int i = 0;
    while (i < g_ntokens) {
        if (g_ncmds >= MSH_MAX_CMDS) {
            snprintf(msg, msg_size, "管道太长（上限 %d 段）", MSH_MAX_CMDS);
            return -1;
        }
        Command *cmd = &g_cmds[g_ncmds];
        memset(cmd, 0, sizeof *cmd);
        if (strcmp(g_tokens[i], "|") == 0) {
            snprintf(msg, msg_size, "管道符前面没有命令");
            return -1;
        }
        while (i < g_ntokens && strcmp(g_tokens[i], "|") != 0) {
            const char *tok = g_tokens[i];
            if (strcmp(tok, "<") == 0 || strcmp(tok, ">") == 0 || strcmp(tok, ">>") == 0) {
                if (i + 1 >= g_ntokens || strcmp(g_tokens[i + 1], "|") == 0) {
                    snprintf(msg, msg_size, "重定向 %s 后面缺少文件名", tok);
                    return -1;
                }
                if (tok[0] == '<') {
                    cmd->in_path = g_tokens[i + 1];
                } else {
                    cmd->out_path = g_tokens[i + 1];
                    cmd->out_append = (tok[1] == '>');
                }
                i += 2;
                continue;
            }
            if (cmd->argc >= MSH_MAX_TOKENS) {
                snprintf(msg, msg_size, "命令参数太多");
                return -1;
            }
            cmd->argv[cmd->argc++] = (char *)tok;
            ++i;
        }
        if (cmd->argc == 0) {
            snprintf(msg, msg_size, "空命令（多的分隔符？）");
            return -1;
        }
        ++g_ncmds;
        if (i < g_ntokens) {          /* 刚吃掉的 '|'：要保证后面还有命令 */
            ++i;
            if (i >= g_ntokens) {
                snprintf(msg, msg_size, "管道符后面没有命令");
                return -1;
            }
        }
    }
    return 0;
}

/* ---------------------------------------------------------------- 内建命令 */

static int is_builtin(const char *name) {
    return strcmp(name, "cd") == 0 || strcmp(name, "exit") == 0 || strcmp(name, "pwd") == 0;
}

static int builtin_cd(Command *cmd) {
    if (cmd->argc > 2) {
        fprintf(stderr, "msh: cd: 参数太多\n");
        return 1;
    }
    const char *dir = cmd->argc > 1 ? cmd->argv[1] : getenv("HOME");
    if (!dir) dir = "/";
    if (chdir(dir) != 0) {
        fprintf(stderr, "msh: cd: %s: %s\n", dir, strerror(errno));
        return 1;
    }
    return 0;
}

static int builtin_pwd(void) {
    char buf[MSH_LINE];
    if (!getcwd(buf, sizeof buf)) {
        fprintf(stderr, "msh: pwd: %s\n", strerror(errno));
        return 1;
    }
    puts(buf);
    return 0;
}

/* ---------------------------------------------------------------- 执行 */

static int run_pipeline(void) {
    pid_t pids[MSH_MAX_CMDS];
    int prev_read = -1;
    for (int i = 0; i < g_ncmds; ++i) {
        Command *cmd = &g_cmds[i];
        int pipefd[2] = {-1, -1};
        if (i + 1 < g_ncmds && pipe(pipefd) != 0) {
            perror("msh: pipe");
            if (prev_read >= 0) close(prev_read);
            return 1;
        }
        pid_t pid = fork();
        if (pid < 0) {
            perror("msh: fork");
            if (prev_read >= 0) close(prev_read);
            if (pipefd[0] >= 0) { close(pipefd[0]); close(pipefd[1]); }
            return 1;
        }
        if (pid == 0) {
            /* 子进程：先接管道，再让重定向覆盖（与真实 shell 次序一致） */
            signal(SIGINT, SIG_DFL);          /* shell 忽略了 SIGINT，子进程要恢复默认 */
            if (prev_read >= 0) {
                if (dup2(prev_read, STDIN_FILENO) < 0) { perror("msh: dup2"); _exit(1); }
                close(prev_read);
            }
            if (i + 1 < g_ncmds) {
                if (dup2(pipefd[1], STDOUT_FILENO) < 0) { perror("msh: dup2"); _exit(1); }
                close(pipefd[0]);
                close(pipefd[1]);
            }
            if (cmd->in_path) {
                int fd = open(cmd->in_path, O_RDONLY);
                if (fd < 0) { fprintf(stderr, "msh: %s: %s\n", cmd->in_path, strerror(errno)); _exit(1); }
                if (dup2(fd, STDIN_FILENO) < 0) { perror("msh: dup2"); _exit(1); }
                close(fd);
            }
            if (cmd->out_path) {
                int flags = O_WRONLY | O_CREAT | (cmd->out_append ? O_APPEND : O_TRUNC);
                int fd = open(cmd->out_path, flags, 0644);
                if (fd < 0) { fprintf(stderr, "msh: %s: %s\n", cmd->out_path, strerror(errno)); _exit(1); }
                if (dup2(fd, STDOUT_FILENO) < 0) { perror("msh: dup2"); _exit(1); }
                close(fd);
            }
            execvp(cmd->argv[0], cmd->argv);
            fprintf(stderr, "msh: %s: %s\n", cmd->argv[0], strerror(errno));
            _exit(127);                       /* 找不到命令：127 是约定 */
        }
        /* 父进程：关掉自己不需要的端 */
        if (prev_read >= 0) close(prev_read);
        if (i + 1 < g_ncmds) {
            close(pipefd[1]);
            prev_read = pipefd[0];
        }
        pids[i] = pid;
    }
    /* 回收**全部**子进程；$? 口径 = 最后一段的状态 */
    int status = 0;
    for (int i = 0; i < g_ncmds; ++i) {
        int st = 0;
        while (waitpid(pids[i], &st, 0) < 0) {
            if (errno != EINTR) { st = 1 << 8; break; }
        }
        if (i == g_ncmds - 1) {
            if (WIFEXITED(st)) status = WEXITSTATUS(st);
            else if (WIFSIGNALED(st)) status = 128 + WTERMSIG(st);
            else status = 1;
        }
    }
    return status;
}

/* ---------------------------------------------------------------- 主循环 */

/* 逐字节读一行：不用 stdio 缓冲，免得把留给子进程（如 cat）的 stdin 预读掉。
 * 返回值：>=0 = 读到的字节数（0 表示空行，也是合法的一行）；-1 = 真 EOF */
static ssize_t read_line(int fd, char *buf, size_t cap) {
    size_t n = 0;
    int consumed = 0;
    for (;;) {
        if (n + 1 >= cap) break;
        char c;
        ssize_t r = read(fd, &c, 1);
        if (r == 0) break;                    /* EOF（可能带着半行，也可能什么都没有） */
        if (r < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        consumed = 1;
        if (c == '\n') break;
        buf[n++] = c;
    }
    if (!consumed) return -1;
    buf[n] = '\0';
    return (ssize_t)n;
}

int main(void) {
    char line[MSH_LINE];
    int last_status = 0;

    signal(SIGINT, SIG_IGN);      /* shell 本体对 Ctrl-C 免疫；子进程在 fork 后恢复默认 */

    for (;;) {
        if (isatty(STDIN_FILENO)) {
            fputs("msh> ", stdout);
            fflush(stdout);
        }
        ssize_t got = read_line(STDIN_FILENO, line, sizeof line);
        if (got < 0) break;       /* EOF：按 $? 退出（空行是 got == 0，不是 EOF！） */

        char *s = line;
        while (*s == ' ' || *s == '\t') ++s;
        if (*s == '\0' || *s == '#') continue;    /* 空行与整行注释 */

        tokens_free();
        if (lex(line) < 0) { last_status = 1; continue; }

        char msg[128];
        if (build_pipeline(msg, sizeof msg) < 0) {
            fprintf(stderr, "msh: 语法错误：%s\n", msg);
            last_status = 1;
            continue;
        }

        if (g_ncmds == 1 && is_builtin(g_cmds[0].argv[0])) {
            const char *name = g_cmds[0].argv[0];
            if (strcmp(name, "exit") == 0) {
                int code = last_status;
                if (g_cmds[0].argc > 1) code = (int)strtol(g_cmds[0].argv[1], NULL, 10);
                tokens_free();
                return code & 0xFF;
            }
            last_status = strcmp(name, "cd") == 0 ? builtin_cd(&g_cmds[0]) : builtin_pwd();
            continue;
        }

        last_status = run_pipeline();
    }
    tokens_free();
    return last_status & 0xFF;
}

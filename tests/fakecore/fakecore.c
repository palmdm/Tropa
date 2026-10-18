/* Test stand-in for an exitFy core library: the same C ABI (StartCore/StopCore),
 * but the work is done by a desktop sing-box process started with the same JSON.
 *   FAKECORE_BIN_<name> / FAKECORE_BIN - program run as "<bin> check|run -c <config>"
 *   FAKECORE_DIR    - where configs and logs go (default /tmp)
 *   $FAKECORE_DIR/<name>.panic - if it exists, StartCore fails like the real core's recovered panic
 *   $FAKECORE_DIR/<name>.panic_if - panic only for configs containing the text in this file
 *   $FAKECORE_DIR/<name>.fail  - if it exists, StartCore returns an ordinary (non-panic) start error
 *   $FAKECORE_DIR/<name>.hang  - if it exists, StartCore never returns (to test timeouts)
 * Compile with -DAPI1 for the legacy ABI (void StopCore). */
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#ifndef CORE_NAME
#define CORE_NAME "fake"
#endif

static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;
static pid_t child = 0;
static unsigned long seq = 0;

static const char *env_or(const char *k, const char *d) {
    const char *v = getenv(k);
    return (v && *v) ? v : d;
}

static int flag_file(const char *dir, const char *suffix) {
    char p[1100];
    snprintf(p, sizeof p, "%s/" CORE_NAME ".%s", dir, suffix);
    return access(p, F_OK) == 0;
}

static char *slurp(const char *path, size_t limit) {
    FILE *f = fopen(path, "rb");
    if (!f) return strdup("");
    char *buf = malloc(limit + 1);
    size_t n = fread(buf, 1, limit, f);
    buf[n] = 0;
    fclose(f);
    return buf;
}

static void append_line(const char *path, const char *line) {
    FILE *f = fopen(path, "a");
    if (!f) return;
    fputs(line, f);
    fputc('\n', f);
    fclose(f);
}

static int run_wait(const char *bin, const char *a1, const char *a2, const char *a3, const char *errpath) {
    pid_t p = fork();
    if (p == 0) {
        int fd = open(errpath, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        int nul = open("/dev/null", O_WRONLY);
        dup2(nul, 1);
        dup2(fd, 2);
        execl(bin, bin, a1, a2, a3, (char *)NULL);
        _exit(127);
    }
    int st = 0;
    waitpid(p, &st, 0);
    return WIFEXITED(st) ? WEXITSTATUS(st) : 255;
}

char *StartCore(const char *cfg) {
    pthread_mutex_lock(&mu);
    if (child > 0) {
        pthread_mutex_unlock(&mu);
        return strdup("SB core is already running or requires StopCore");
    }
    const char *dir = env_or("FAKECORE_DIR", "/tmp");
    char path[1024], errp[1100], logp[1100];
    snprintf(path, sizeof path, "%s/" CORE_NAME "-%d-%lu.json", dir, (int)getpid(), ++seq);
    snprintf(errp, sizeof errp, "%s.err", path);
    snprintf(logp, sizeof logp, "%s/" CORE_NAME "-calls.log", dir);
    FILE *f = fopen(path, "w");
    if (f) { fputs(cfg ? cfg : "", f); fclose(f); }
    append_line(logp, path);
    {
        char pi[1100];
        snprintf(pi, sizeof pi, "%s/" CORE_NAME ".panic_if", dir);
        char *needle = access(pi, F_OK) == 0 ? slurp(pi, 200) : NULL;
        int hit = needle && *needle && cfg && strstr(cfg, needle);
        free(needle);
        if (hit) {
            pthread_mutex_unlock(&mu);
            return strdup("SB core start panic: runtime error: index out of range [1] with length 1");
        }
    }
    if (flag_file(dir, "panic")) {
        pthread_mutex_unlock(&mu);
        return strdup("SB core start panic: runtime error: invalid memory address or nil pointer dereference");
    }
    if (flag_file(dir, "fail")) {
        pthread_mutex_unlock(&mu);
        return strdup("start SB core: initialize network monitor: permission denied");
    }
    if (flag_file(dir, "hang")) {
        pthread_mutex_unlock(&mu);
        for (;;) sleep(1000);
    }
    const char *bin = env_or("FAKECORE_BIN_" CORE_NAME, env_or("FAKECORE_BIN", "sing-box"));
    if (run_wait(bin, "check", "-c", path, errp) != 0) {
        char *e = slurp(errp, 4000);
        size_t n = strlen(e) + 64;
        char *out = malloc(n);
        snprintf(out, n, "create SB core: %s", e);
        free(e);
        pthread_mutex_unlock(&mu);
        return out;
    }
    pid_t p = fork();
    if (p == 0) {
        int fd = open(errp, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        int nul = open("/dev/null", O_WRONLY);
        dup2(nul, 1);
        dup2(fd, 2);
        execl(bin, bin, "run", "-c", path, (char *)NULL);
        _exit(127);
    }
    struct timespec ts = {0, 150 * 1000 * 1000};
    nanosleep(&ts, NULL);
    int st = 0;
    if (waitpid(p, &st, WNOHANG) == p) {
        char *e = slurp(errp, 4000);
        size_t n = strlen(e) + 64;
        char *out = malloc(n);
        snprintf(out, n, "start SB core: %s", e);
        free(e);
        pthread_mutex_unlock(&mu);
        return out;
    }
    child = p;
    pthread_mutex_unlock(&mu);
    return NULL;
}

static void stop_child(void) {
    pthread_mutex_lock(&mu);
    if (child > 0) {
        kill(child, SIGTERM);
        int st = 0;
        for (int i = 0; i < 100; i++) {
            if (waitpid(child, &st, WNOHANG) == child) break;
            struct timespec ts = {0, 20 * 1000 * 1000};
            nanosleep(&ts, NULL);
            if (i == 99) { kill(child, SIGKILL); waitpid(child, &st, 0); }
        }
        child = 0;
    }
    pthread_mutex_unlock(&mu);
}

#ifdef API1
void StopCore(void) { stop_child(); }
#else
char *StopCore(void) { stop_child(); return NULL; }
#endif

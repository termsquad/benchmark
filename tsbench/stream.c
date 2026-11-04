#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <math.h>
#include <omp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static double now_seconds(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

static int parse_positive(const char *input, long min, long max, long *out) {
    char *end = NULL;
    errno = 0;
    long n = strtol(input, &end, 10);
    if (errno || end == input || *end || n < min || n > max) return 0;
    *out = n;
    return 1;
}

int main(int argc, char **argv) {
    long threads, mib, seconds;
    if (argc != 4 ||
        !parse_positive(argv[1], 1, 1024, &threads) ||
        !parse_positive(argv[2], 64, 32768, &mib) ||
        !parse_positive(argv[3], 1, 60, &seconds)) {
        fputs("usage: tsbench-stream THREADS WORKING_SET_MIB SECONDS\n", stderr);
        return 2;
    }
    const size_t n = (size_t)mib * 1024u * 1024u / (3u * sizeof(double));
    if (n == 0 || n > SIZE_MAX / sizeof(double)) return 2;
    const size_t bytes = n * sizeof(double);
    double *a = NULL, *b = NULL, *c = NULL;
    if (posix_memalign((void **)&a, 64, bytes) ||
        posix_memalign((void **)&b, 64, bytes) ||
        posix_memalign((void **)&c, 64, bytes)) {
        fputs("memory allocation failed\n", stderr);
        free(a); free(b); free(c);
        return 3;
    }
    omp_set_dynamic(0);
    omp_set_num_threads((int)threads);
    #pragma omp parallel for schedule(static)
    for (size_t i = 0; i < n; ++i) {
        a[i] = 1.0 + (double)(i % 19) / 19.0;
        b[i] = 2.0;
        c[i] = 0.0;
    }

    double elapsed[4] = {0, 0, 0, 0};
    double started = now_seconds();
    long passes = 0;
    for (; passes < 100000; ++passes) {
        double t = now_seconds();
        #pragma omp parallel for schedule(static)
        for (size_t i = 0; i < n; ++i) c[i] = a[i];
        elapsed[0] += now_seconds() - t;
        t = now_seconds();
        #pragma omp parallel for schedule(static)
        for (size_t i = 0; i < n; ++i) b[i] = 0.5 * c[i];
        elapsed[1] += now_seconds() - t;
        t = now_seconds();
        #pragma omp parallel for schedule(static)
        for (size_t i = 0; i < n; ++i) c[i] = a[i] + b[i];
        elapsed[2] += now_seconds() - t;
        t = now_seconds();
        #pragma omp parallel for schedule(static)
        for (size_t i = 0; i < n; ++i) a[i] = b[i] + 0.25 * c[i];
        elapsed[3] += now_seconds() - t;
        if (passes >= 4 && now_seconds() - started >= (double)seconds) {
            ++passes;
            break;
        }
    }
    double checksum = 0;
    for (size_t i = 0; i < n; i += n / 1024 + 1)
        checksum += a[i] + b[i] + c[i];
    const double mib_per_pass = (double)bytes / (1024.0 * 1024.0);
    if (!isfinite(checksum) || checksum <= 0) {
        fputs("invalid checksum\n", stderr);
        free(a); free(b); free(c);
        return 4;
    }
    printf("{\"backend\":\"stream_style_v1\",\"threads\":%ld,\"working_set_mib\":%ld,"
           "\"passes\":%ld,\"wall_seconds\":%.6f,\"checksum\":%.9g,"
           "\"copy_mib_per_sec\":%.4f,\"scale_mib_per_sec\":%.4f,"
           "\"add_mib_per_sec\":%.4f,\"triad_mib_per_sec\":%.4f}\n",
           threads,mib,passes,now_seconds()-started,checksum,
           2*mib_per_pass*passes/elapsed[0],
           2*mib_per_pass*passes/elapsed[1],
           3*mib_per_pass*passes/elapsed[2],
           3*mib_per_pass*passes/elapsed[3]);
    free(a); free(b); free(c);
    return 0;
}

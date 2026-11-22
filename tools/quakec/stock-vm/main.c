/* CLI host for id Software's unmodified WinQuake/pr_exec.c.
 * GPL-2.0-or-later, like the interpreter it hosts. See LICENSE.txt.
 */
#include "quakedef.h"
#include <errno.h>

_Static_assert(sizeof(float) == 4 && sizeof(int) == 4, "32-bit VM words required");
_Static_assert(sizeof(dprograms_t) == 60, "unexpected program header layout");
_Static_assert(sizeof(dstatement_t) == 8, "unexpected statement layout");
_Static_assert(sizeof(dfunction_t) == 36, "unexpected function layout");

server_t sv;
dprograms_t *progs;
dfunction_t *pr_functions;
dstatement_t *pr_statements;
float *pr_globals;
globalvars_t *pr_global_struct;
char *pr_strings;
static builtin_t builtin_table[79];
builtin_t *pr_builtins = builtin_table;
int pr_numbuiltins = 79;
static size_t edict_size;

static _Noreturn void fail(char *format, va_list args)
{
    fputs("stock-vm: ", stderr);
    vfprintf(stderr, format, args);
    fputc('\n', stderr);
    exit(2);
}

_Noreturn void Host_Error(char *format, ...)
{
    va_list args;
    va_start(args, format);
    fail(format, args);
}

_Noreturn void Sys_Error(char *format, ...)
{
    va_list args;
    va_start(args, format);
    fail(format, args);
}

void Con_Printf(char *format, ...)
{
    va_list args;
    va_start(args, format);
    vprintf(format, args);
    va_end(args);
}

edict_t *Stock_Edict(int offset)
{
    if (offset < 0 || (size_t)offset % edict_size || (size_t)offset / edict_size >= 600)
        Host_Error("invalid entity reference %d", offset);
    return (edict_t *)((byte *)sv.edicts + offset);
}

void ED_Print(edict_t *entity)
{
    printf("entity at byte offset %td\n", (byte *)entity - (byte *)sv.edicts);
}

char *PR_GlobalString(int offset)
{
    static char buffers[4][48];
    static unsigned int next;
    char *buffer = buffers[next++ % 4];
    snprintf(buffer, 48, "global[%d]", offset);
    return buffer;
}

char *PR_GlobalStringNoContents(int offset) { return PR_GlobalString(offset); }

static const char *string_at(int offset)
{
    if (offset < 0 || offset >= progs->numstrings ||
        !memchr(pr_strings + offset, 0, progs->numstrings - offset))
        Host_Error("invalid string offset %d", offset);
    return pr_strings + offset;
}

static void unsupported_builtin(void)
{
    int function;
    dstatement_t *statement = pr_statements + pr_xstatement;
    memcpy(&function, pr_globals + statement->a, sizeof(function));
    Host_Error("builtin #%d (%s) requires the game engine; unavailable in CLI host",
               -pr_functions[function].first_statement,
               string_at(pr_functions[function].s_name));
}

/* There is no server developer cvar: dprint text is always printed so compiler
 * tests can observe it.
 */
static void debug_print(void)
{
    for (int i = 0; i < pr_argc; ++i) {
        int offset;
        memcpy(&offset, pr_globals + OFS_PARM0 + 3 * i, sizeof(offset));
        fputs(string_at(offset), stdout);
    }
}

static void program_error(void)
{
    fputs("stock-vm: ", stderr);
    for (int i = 0; i < pr_argc; ++i) {
        int offset;
        memcpy(&offset, pr_globals + OFS_PARM0 + 3 * i, sizeof(offset));
        fputs(string_at(offset), stderr);
    }
    fputc('\n', stderr);
    exit(2);
}

static void check_section(size_t length, int offset, int count, size_t stride)
{
    if (offset < 60 || count < 0 || (size_t)offset > length ||
        (size_t)count > (length - (size_t)offset) / stride)
        Host_Error("invalid program section; run tools/quakec/check-stock.py first");
}

static void load_program(const char *path)
{
    unsigned int endian = 1;
    if (*(byte *)&endian != 1)
        Host_Error("CLI host currently requires a little-endian machine");
    FILE *file = fopen(path, "rb");
    if (!file)
        Host_Error("cannot open %s: %s", path, strerror(errno));
    if (fseek(file, 0, SEEK_END))
        Host_Error("cannot seek %s", path);
    long size = ftell(file);
    if (size < 60 || fseek(file, 0, SEEK_SET))
        Host_Error("invalid program file %s", path);
    byte *data = malloc((size_t)size);
    if (!data || fread(data, 1, (size_t)size, file) != (size_t)size)
        Host_Error("cannot read %s", path);
    fclose(file);
    progs = (dprograms_t *)data;
    if (progs->version != 6 || progs->crc != PROGHEADER_CRC)
        Host_Error("expected stock Quake version 6 and ABI CRC 5927");
    check_section(size, progs->ofs_statements, progs->numstatements, 8);
    check_section(size, progs->ofs_functions, progs->numfunctions, 36);
    check_section(size, progs->ofs_strings, progs->numstrings, 1);
    check_section(size, progs->ofs_globals, progs->numglobals, 4);
    if (progs->numglobals < (int)(sizeof(globalvars_t) / 4) || progs->numglobals > 32768 ||
        progs->entityfields < (int)(sizeof(entvars_t) / 4) || progs->entityfields > 32768)
        Host_Error("invalid stock global/entity storage size");
    pr_functions = (dfunction_t *)(data + progs->ofs_functions);
    pr_statements = (dstatement_t *)(data + progs->ofs_statements);
    pr_strings = (char *)(data + progs->ofs_strings);
    pr_globals = (float *)(data + progs->ofs_globals);
    pr_global_struct = (globalvars_t *)pr_globals;
    edict_size = (size_t)progs->entityfields * 4;
    sv.edicts = calloc(600, edict_size);
    if (!sv.edicts)
        Host_Error("cannot allocate entity storage");
    sv.state = ss_active;
    for (int i = 0; i < pr_numbuiltins; ++i)
        builtin_table[i] = unsupported_builtin;
    builtin_table[25] = debug_print;
    builtin_table[10] = program_error;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s PROGS.DAT FUNCTION [FLOAT ...]\n"
                        "       %s PROGS.DAT --list\n", argv[0], argv[0]);
        return 2;
    }
    load_program(argv[1]);
    for (int i = 1; i < progs->numfunctions; ++i) {
        dfunction_t *function = pr_functions + i;
        const char *name = string_at(function->s_name);
        if (!strcmp(argv[2], "--list")) {
            printf("%s%s\n", name, function->first_statement < 0 ? " [builtin]" : "");
            continue;
        }
        if (strcmp(name, argv[2]))
            continue;
        if (function->first_statement <= 0 || function->numparms < 0 || function->numparms > 8)
            Host_Error("entry must be a bytecode function with at most eight parameters");
        if (argc - 3 != function->numparms)
            Host_Error("%s expects %d arguments, got %d", name, function->numparms, argc - 3);
        for (int p = 0; p < function->numparms; ++p) {
            char *end;
            if (function->parm_size[p] != 1)
                Host_Error("CLI arguments currently support scalar floats only");
            errno = 0;
            float value = strtof(argv[p + 3], &end);
            if (errno || end == argv[p + 3] || *end)
                Host_Error("invalid float argument: %s", argv[p + 3]);
            pr_globals[OFS_PARM0 + 3 * p] = value;
        }
        PR_ExecuteProgram(i);
        printf("return: %.9g\n", pr_globals[OFS_RETURN]);
        long long instructions = 0;
        for (int f = 0; f < progs->numfunctions; ++f)
            instructions += pr_functions[f].profile;
        printf("instructions: %lld\n", instructions);
        return 0;
    }
    if (!strcmp(argv[2], "--list"))
        return 0;
    Host_Error("function not found: %s", argv[2]);
}

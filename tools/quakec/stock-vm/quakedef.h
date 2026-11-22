/* Minimal host interface for the unmodified stock WinQuake interpreter.
 * This is a test host, not a replacement for Quake's engine or builtin table.
 */
#ifndef STOCK_VM_HOST_H
#define STOCK_VM_HOST_H

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned char byte;
typedef float vec3_t[3];
typedef int qboolean;
enum { false = 0, true = 1, ss_loading = 1, ss_active = 2 };

#include "pr_comp.h"
#include "progdefs.q1"

typedef union {
    string_t string;
    float _float;
    float vector[3];
    func_t function;
    int _int;
    int edict;
} eval_t;

typedef struct { entvars_t v; } edict_t;
typedef struct { edict_t *edicts; int state; } server_t;
typedef void (*builtin_t)(void);

extern server_t sv;
extern dprograms_t *progs;
extern dfunction_t *pr_functions;
extern dstatement_t *pr_statements;
extern float *pr_globals;
extern globalvars_t *pr_global_struct;
extern char *pr_strings;
extern builtin_t *pr_builtins;
extern int pr_numbuiltins, pr_argc, pr_xstatement, pr_depth;

edict_t *Stock_Edict(int offset);
#define PROG_TO_EDICT(offset) Stock_Edict(offset)
void Con_Printf(char *format, ...);
_Noreturn void Host_Error(char *format, ...);
_Noreturn void Sys_Error(char *format, ...);
void ED_Print(edict_t *entity);
char *PR_GlobalString(int offset);
char *PR_GlobalStringNoContents(int offset);
void PR_ExecuteProgram(func_t function);

#endif

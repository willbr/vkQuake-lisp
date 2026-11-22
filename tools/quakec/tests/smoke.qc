// Small programs exercised by the stock interpreter CLI.
float(float value) stock_twice =
{
    return value * 2;
};

float() stock_smoke =
{
    local vector a, b, result;
    local float i, sum;
    a = '1 2 3';
    b = '4 5 6';
    result = a + b;
    if (result != '5 7 9')
        return -1;
    i = 0;
    sum = 0;
    while (i < 10)
    {
        sum = sum + i;
        i = i + 1;
    }
    if (sum != 45)
        return -2;
    dprint("stock CLI smoke ok\n");
    return stock_twice(21);
};

void() stock_watchdog =
{
    while (1) {}
};

void() stock_overflow =
{
    stock_overflow();
};

void() stock_engine_builtin =
{
    precache_model("progs/player.mdl");
};

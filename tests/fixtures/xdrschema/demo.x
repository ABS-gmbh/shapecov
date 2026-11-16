// A small XDR file covering each construct tools/xdrschema.py handles.
%#include "xdr/Stellar-types.h"

namespace stellar
{
const MAX_NAMES = 4;

typedef opaque Hash[32];
typedef unsigned hyper TimePoint;

enum Color
{
    RED = 0,
    GREEN = 1,
    BLUE = 0x10
};

/* a struct with every field shape */
struct Thing
{
    int a;
    unsigned int b;
    hyper c;
    bool d;
    Hash h;
    opaque blob<>;
    string name<MAX_NAMES>;
    Color colors<MAX_NAMES>;
    TimePoint *maybe;
    int pair[2];
    union switch (int v)
    {
    case 0:
        void;
    case 1:
        int one;
    } ext;
};

union Choice switch (Color c)
{
case RED:
case GREEN:
    Thing thing;
case BLUE:
    void;
default:
    int other;
};
}

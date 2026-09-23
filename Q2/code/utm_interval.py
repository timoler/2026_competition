"""Interval derivative signs for local WGS84 inverse-UTM straight segments.

Sixth-order Krueger beta coefficients: Karney, GeographicLib,
https://github.com/geographiclib/geographiclib/blob/main/src/TransverseMercator.cpp
The coordinate evaluation remains PROJ; these intervals reject paths for which
native longitude/latitude monotonicity cannot be established numerically.
"""
from mpmath import iv


def monotonic_signs(a, b):
    iv.dps = 30
    # Scope guard: local northern UTM 49N domain, well inside UTM series range.
    if not all(250000 < p[0] < 400000 and 2400000 < p[1] < 2700000 for p in (a,b)):
        raise ValueError("Outside certified local UTM domain")
    n = (1 / iv.mpf("298.257223563")) / (2 - 1 / iv.mpf("298.257223563"))
    scale = iv.mpf("0.9996") * iv.mpf(6378137)/(1+n)*(1+n**2/4+n**4/64+n**6/256)
    beta = [
        n/2-2*n**2/3+37*n**3/96-n**4/360-81*n**5/512+96199*n**6/604800,
        n**2/48+n**3/15-437*n**4/1440+46*n**5/105-1118711*n**6/3870720,
        17*n**3/480-37*n**4/840-209*n**5/4480+5569*n**6/90720,
        4397*n**4/161280-11*n**5/504-830251*n**6/7257600,
        4583*n**5/161280-108847*n**6/3991680,
        20648693*n**6/638668800]
    xi = iv.mpf(sorted([a[1],b[1]]))/scale
    eta = (iv.mpf(sorted([a[0],b[0]]))-500000)/scale
    dxi, deta = (b[1]-a[1])/scale, (b[0]-a[0])/scale
    sinh = lambda v: (iv.exp(v)-iv.exp(-v))/2
    cosh = lambda v: (iv.exp(v)+iv.exp(-v))/2
    xp, ep, diagonal, cross = xi, eta, iv.mpf(1), iv.mpf(0)
    for j, bj in enumerate(beta,1):
        xp -= bj*iv.sin(2*j*xi)*cosh(2*j*eta)
        ep -= bj*iv.cos(2*j*xi)*sinh(2*j*eta)
        diagonal -= 2*j*bj*iv.cos(2*j*xi)*cosh(2*j*eta)
        cross += 2*j*bj*iv.sin(2*j*xi)*sinh(2*j*eta)
    dxp, dep = dxi*diagonal-deta*cross, deta*diagonal+dxi*cross
    # Denominators and inverse conformal-latitude derivative are positive.
    longitude = iv.cos(xp)*cosh(ep)*dep+sinh(ep)*iv.sin(xp)*dxp
    latitude = iv.cos(xp)*cosh(ep)**2*dxp-iv.sin(xp)*sinh(ep)*cosh(ep)*dep
    signs = []
    for value in (longitude, latitude):
        lo, hi = float(value.a), float(value.b)
        # Margin exceeds rounding/series effects in this local sixth-order model.
        if lo > 1e-11:
            signs.append(1)
        elif hi < -1e-11:
            signs.append(-1)
        else:
            raise ValueError("Inverse-UTM derivative sign not certified; cannot enumerate cells")
    return signs

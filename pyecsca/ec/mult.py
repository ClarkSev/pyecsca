from copy import copy
from typing import Mapping, Tuple, Optional, MutableMapping, Union

from public import public

from .context import getcontext
from .formula import (Formula, AdditionFormula, DoublingFormula, DifferentialAdditionFormula,
                      ScalingFormula, LadderFormula, NegationFormula)
from .group import AbelianGroup
from .naf import naf, wnaf
from .point import Point


class ScalarMultiplier(object):
    """
    A scalar multiplication algorithm.

    :param short_circuit: Whether the use of formulas will be guarded by short-circuit on inputs
                          of the point at infinity.
    :param formulas: Formulas this instance will use.
    """
    short_circuit: bool
    formulas: Mapping[str, Formula]
    _group: AbelianGroup
    _point: Point = None

    def __init__(self, short_circuit=True, **formulas: Optional[Formula]):
        if len(set(formula.coordinate_model for formula in formulas.values() if
                   formula is not None)) != 1:
            raise ValueError
        self.short_circuit = short_circuit
        self.formulas = dict(filter(lambda pair: pair[1] is not None, formulas.items()))

    def _add(self, one: Point, other: Point) -> Point:
        if "add" not in self.formulas:
            raise NotImplementedError
        if self.short_circuit:
            if one == self._group.neutral:
                return copy(other)
            if other == self._group.neutral:
                return copy(one)
        return \
            getcontext().execute(self.formulas["add"], one, other, **self._group.curve.parameters)[0]

    def _dbl(self, point: Point) -> Point:
        if "dbl" not in self.formulas:
            raise NotImplementedError
        if self.short_circuit:
            if point == self._group.neutral:
                return copy(point)
        return getcontext().execute(self.formulas["dbl"], point, **self._group.curve.parameters)[0]

    def _scl(self, point: Point) -> Point:
        if "scl" not in self.formulas:
            raise NotImplementedError
        return getcontext().execute(self.formulas["scl"], point, **self._group.curve.parameters)[0]

    def _ladd(self, start: Point, to_dbl: Point, to_add: Point) -> Tuple[Point, ...]:
        if "ladd" not in self.formulas:
            raise NotImplementedError
        return getcontext().execute(self.formulas["ladd"], start, to_dbl, to_add,
                                    **self._group.curve.parameters)

    def _dadd(self, start: Point, one: Point, other: Point) -> Point:
        if "dadd" not in self.formulas:
            raise NotImplementedError
        if self.short_circuit:
            if one == self._group.neutral:
                return copy(other)
            if other == self._group.neutral:
                return copy(one)
        return getcontext().execute(self.formulas["dadd"], start, one, other,
                                    **self._group.curve.parameters)[0]

    def _neg(self, point: Point) -> Point:
        if "neg" not in self.formulas:
            raise NotImplementedError
        return getcontext().execute(self.formulas["neg"], point, **self._group.curve.parameters)[0]

    def init(self, group: AbelianGroup, point: Point):
        coord_model = set(self.formulas.values()).pop().coordinate_model
        if group.curve.coordinate_model != coord_model or point.coordinate_model != coord_model:
            raise ValueError
        self._group = group
        self._point = point

    def multiply(self, scalar: int) -> Point:
        raise NotImplementedError


@public
class LTRMultiplier(ScalarMultiplier):
    """
    Classic double and add scalar multiplication algorithm, that scans the scalar left-to-right (msb to lsb)

    The `always` parameter determines whether the double and add always method is used.
    """
    always: bool

    def __init__(self, add: AdditionFormula, dbl: DoublingFormula,
                 scl: ScalingFormula = None, always: bool = False):
        super().__init__(add=add, dbl=dbl, scl=scl)
        self.always = always

    def multiply(self, scalar: int) -> Point:
        if scalar == 0:
            return copy(self._group.neutral)
        q = self._point
        r = copy(self._group.neutral)
        for i in range(scalar.bit_length() - 1, -1, -1):
            r = self._dbl(r)
            if scalar & (1 << i) != 0:
                r = self._add(r, q)
            elif self.always:
                self._add(r, q)
        if "scl" in self.formulas:
            r = self._scl(r)
        return r


@public
class RTLMultiplier(ScalarMultiplier):
    """
    Classic double and add scalar multiplication algorithm, that scans the scalar right-to-left (lsb to msb)

    The `always` parameter determines whether the double and add always method is used.
    """
    always: bool

    def __init__(self, add: AdditionFormula, dbl: DoublingFormula,
                 scl: ScalingFormula = None, always: bool = False):
        super().__init__(add=add, dbl=dbl, scl=scl)
        self.always = always

    def multiply(self, scalar: int) -> Point:
        if scalar == 0:
            return copy(self._group.neutral)
        q = self._point
        r = copy(self._group.neutral)
        while scalar > 0:
            if scalar & 1 != 0:
                r = self._add(r, q)
            elif self.always:
                self._add(r, q)
            q = self._dbl(q)
            scalar >>= 1
        if "scl" in self.formulas:
            r = self._scl(r)
        return r


class CoronMultiplier(ScalarMultiplier):
    """
    Coron's double and add resistant against SPA, from:

    Resistance against Differential Power Analysis for Elliptic Curve Cryptosystems

    https://link.springer.com/content/pdf/10.1007/3-540-48059-5_25.pdf
    """

    def __init__(self, add: AdditionFormula, dbl: DoublingFormula, scl: ScalingFormula = None):
        super().__init__(add=add, dbl=dbl, scl=scl)

    def multiply(self, scalar: int) -> Point:
        if scalar == 0:
            return copy(self._group.neutral)
        q = self._point
        p0 = copy(q)
        for i in range(scalar.bit_length() - 2, -1, -1):
            p0 = self._dbl(p0)
            p1 = self._add(p0, q)
            if scalar & (1 << i) != 0:
                p0 = p1
        if "scl" in self.formulas:
            p0 = self._scl(p0)
        return p0


@public
class LadderMultiplier(ScalarMultiplier):
    """
    Montgomery ladder multiplier, using a three input, two output ladder formula.
    """

    def __init__(self, ladd: LadderFormula, dbl: DoublingFormula, scl: ScalingFormula = None):
        super().__init__(ladd=ladd, dbl=dbl, scl=scl)

    def multiply(self, scalar: int) -> Point:
        if scalar == 0:
            return copy(self._group.neutral)
        q = self._point
        p0 = copy(q)
        p1 = self._dbl(q)
        for i in range(scalar.bit_length() - 2, -1, -1):
            if scalar & (1 << i) == 0:
                p0, p1 = self._ladd(q, p0, p1)
            else:
                p1, p0 = self._ladd(q, p1, p0)
        if "scl" in self.formulas:
            p0 = self._scl(p0)
        return p0


@public
class SimpleLadderMultiplier(ScalarMultiplier):
    """
    Montgomery ladder multiplier, using addition and doubling formulas.
    """
    _differential: bool = False

    def __init__(self, add: Union[AdditionFormula, DifferentialAdditionFormula], dbl: DoublingFormula,
                 scl: ScalingFormula = None):
        if isinstance(add, AdditionFormula):
            super().__init__(add=add, dbl=dbl, scl=scl)
        elif isinstance(add, DifferentialAdditionFormula):
            super().__init__(dadd=add, dbl=dbl, scl=scl)
            self._differential = True
        else:
            raise ValueError

    def multiply(self, scalar: int) -> Point:
        if scalar == 0:
            return copy(self._group.neutral)
        q = self._point
        p0 = copy(self._group.neutral)
        p1 = copy(q)
        for i in range(scalar.bit_length() - 1, -1, -1):
            if scalar & (1 << i) == 0:
                if self._differential:
                    p1 = self._dadd(q, p0, p1)
                else:
                    p1 = self._add(p0, p1)
                p0 = self._dbl(p0)
            else:
                if self._differential:
                    p0 = self._dadd(q, p0, p1)
                else:
                    p0 = self._add(p0, p1)
                p1 = self._dbl(p1)
        if "scl" in self.formulas:
            p0 = self._scl(p0)
        return p0


@public
class BinaryNAFMultiplier(ScalarMultiplier):
    """
    Binary NAF (Non Adjacent Form) multiplier, left-to-right.
    """
    _point_neg: Point

    def __init__(self, add: AdditionFormula, dbl: DoublingFormula,
                 neg: NegationFormula, scl: ScalingFormula = None):
        super().__init__(add=add, dbl=dbl, neg=neg, scl=scl)

    def init(self, group: AbelianGroup, point: Point):
        super().init(group, point)
        self._point_neg = self._neg(point)

    def multiply(self, scalar: int) -> Point:
        if scalar == 0:
            return copy(self._group.neutral)
        bnaf = naf(scalar)
        q = copy(self._group.neutral)
        for val in bnaf:
            q = self._dbl(q)
            if val == 1:
                q = self._add(q, self._point)
            if val == -1:
                q = self._add(q, self._point_neg)
        if "scl" in self.formulas:
            q = self._scl(q)
        return q


@public
class WindowNAFMultiplier(ScalarMultiplier):
    """
    Window NAF (Non Adjacent Form) multiplier, left-to-right.
    """
    _points: MutableMapping[int, Point]
    _points_neg: MutableMapping[int, Point]
    _precompute_neg: bool = False
    _width: int

    def __init__(self, add: AdditionFormula, dbl: DoublingFormula,
                 neg: NegationFormula, width: int, scl: ScalingFormula = None,
                 precompute_negation: bool = False):
        super().__init__(add=add, dbl=dbl, neg=neg, scl=scl)
        self._width = width
        self._precompute_neg = precompute_negation

    def init(self, group: AbelianGroup, point: Point):
        super().init(group, point)
        self._points = {}
        self._points_neg = {}
        current_point = point
        double_point = self._dbl(point)
        for i in range(1, (self._width + 1) // 2 + 1):
            self._points[2 ** i - 1] = current_point
            if self._precompute_neg:
                self._points_neg[2 ** i - 1] = self._neg(current_point)
            current_point = self._add(current_point, double_point)

    def multiply(self, scalar: int) -> Point:
        if scalar == 0:
            return copy(self._group.neutral)
        naf = wnaf(scalar, self._width)
        q = copy(self._group.neutral)
        for val in naf:
            q = self._dbl(q)
            if val > 0:
                q = self._add(q, self._points[val])
            elif val < 0:
                if self._precompute_neg:
                    neg = self._points_neg[-val]
                else:
                    neg = self._neg(self._points[-val])
                q = self._add(q, neg)
        if "scl" in self.formulas:
            q = self._scl(q)
        return q

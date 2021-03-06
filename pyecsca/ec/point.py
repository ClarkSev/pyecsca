from copy import copy
from typing import Mapping, Any

from public import public

from .context import ResultAction
from .coordinates import AffineCoordinateModel, CoordinateModel
from .mod import Mod, Undefined
from .op import CodeOp


@public
class CoordinateMappingAction(ResultAction):
    """A mapping of a point from one coordinate system to another one, usually one is an affine one."""
    model_from: CoordinateModel
    model_to: CoordinateModel
    point: "Point"

    def __init__(self, model_from: CoordinateModel, model_to: CoordinateModel, point: "Point"):
        super().__init__()
        self.model_from = model_from
        self.model_to = model_to
        self.point = point

    def __repr__(self):
        return f"{self.__class__.__name__}(from={self.model_from}, to={self.model_to}, {self.point})"


@public
class Point(object):
    """A point with coordinates in a coordinate model."""
    coordinate_model: CoordinateModel
    coords: Mapping[str, Mod]

    def __init__(self, model: CoordinateModel, **coords: Mod):
        if not set(model.variables) == set(coords.keys()):
            raise ValueError
        self.coordinate_model = model
        self.coords = coords

    def __getattribute__(self, name):
        if "coords" in super().__getattribute__("__dict__"):
            coords = super().__getattribute__("coords")
            if name in coords:
                return coords[name]
        return super().__getattribute__(name)

    def to_affine(self) -> "Point":
        """Convert this point into the affine coordinate model, if possible."""
        affine_model = AffineCoordinateModel(self.coordinate_model.curve_model)
        with CoordinateMappingAction(self.coordinate_model, affine_model, self) as action:
            if isinstance(self.coordinate_model, AffineCoordinateModel):
                return action.exit(copy(self))
            ops = []
            for s in self.coordinate_model.satisfying:
                try:
                    ops.append(CodeOp(s))
                except Exception:
                    pass
            result_variables = set(map(lambda x: x.result, ops))
            if not result_variables.issuperset(affine_model.variables):
                raise NotImplementedError
            result = {}
            locls = {**self.coords}
            for op in ops:
                try:
                    locls[op.result] = op(**locls)
                except NameError as e:
                    if op.result in affine_model.variables:
                        raise e
                    else:
                        continue
                if op.result in affine_model.variables:
                    result[op.result] = locls[op.result]
            return action.exit(Point(affine_model, **result))

    def to_model(self, coordinate_model: CoordinateModel, curve: "EllipticCurve") -> "Point":
        """Convert an affine point into a given coordinate model, if possible."""
        if not isinstance(self.coordinate_model, AffineCoordinateModel):
            raise ValueError
        with CoordinateMappingAction(self.coordinate_model, coordinate_model, self) as action:
            ops = []
            for s in coordinate_model.satisfying:
                try:
                    ops.append(CodeOp(s))
                except Exception:
                    pass
            locls = {**self.coords, **curve.parameters, "Z": Mod(1, curve.prime)}
            for op in ops:
                try:
                    locls[op.result] = op(**locls)
                except:
                    continue
            result = {}
            for var in coordinate_model.variables:  
                if var in locls:  # Try this first.
                    result[var] = locls[var]
                elif var == "X":  #  XXX: This just works for the stuff currently in EFD.
                    result[var] = self.coords["x"]
                elif var == "Y":
                    result[var] = self.coords["y"]
                elif var.startswith("Z"):
                    result[var] = Mod(1, curve.prime)
                elif var == "T":
                    result[var] = Mod(int(affine_point.coords["x"] * affine_point.coords["y"]), curve.prime)
                else:
                    raise NotImplementedError
            return action.exit(Point(coordinate_model, **result))

    def equals(self, other: Any) -> bool:
        """Test whether this point is equal to `other` irrespective of the coordinate model (in the affine sense)."""
        if not isinstance(other, Point):
            return False
        if self.coordinate_model.curve_model != other.coordinate_model.curve_model:
            return False
        return self.to_affine() == other.to_affine()

    def __bytes__(self):
        res = b"\x04"
        for k in sorted(self.coords.keys()):
            res += bytes(self.coords[k])
        return res

    def __eq__(self, other):
        if not isinstance(other, Point):
            return False
        if self.coordinate_model != other.coordinate_model:
            return False
        return self.coords == other.coords

    def __hash__(self):
        return hash(self.coords) + 1

    def __str__(self):
        args = ", ".join([f"{key}={val}" for key, val in self.coords.items()])
        return f"[{args}]"

    def __repr__(self):
        return f"Point([{str(self)}] in {self.coordinate_model})"


@public
class InfinityPoint(Point):
    """A point at infinity."""

    def __init__(self, model: CoordinateModel):
        coords = {key: Undefined() for key in model.variables}
        super().__init__(model, **coords)

    def to_affine(self) -> "InfinityPoint":
        return InfinityPoint(AffineCoordinateModel(self.coordinate_model.curve_model))

    def to_model(self, coordinate_model: CoordinateModel, curve: "EllipticCurve") -> "InfinityPoint":
        return InfinityPoint(coordinate_model)

    def equals(self, other) -> bool:
        return self == other

    def __bytes__(self):
        return b"\x00"

    def __eq__(self, other):
        if type(other) is not InfinityPoint:
            return False
        else:
            return self.coordinate_model == other.coordinate_model

    def __str__(self):
        return "Infinity"

    def __repr__(self):
        return f"InfinityPoint({self.coordinate_model})"

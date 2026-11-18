use pyo3::prelude::*;
use nalgebra::{Matrix3, Vector3};

/// A 3D point/vector used by the geometry engine.
#[pyclass]
#[derive(Clone, Debug)]
pub struct Vec3 {
    #[pyo3(get, set)]
    pub x: f64,
    #[pyo3(get, set)]
    pub y: f64,
    #[pyo3(get, set)]
    pub z: f64,
}

#[pymethods]
impl Vec3 {
    #[new]
    fn new(x: f64, y: f64, z: f64) -> Self {
        Vec3 { x, y, z }
    }

    fn __repr__(&self) -> String {
        format!("Vec3({:.4}, {:.4}, {:.4})", self.x, self.y, self.z)
    }

    fn __add__(&self, other: &Vec3) -> Vec3 {
        Vec3 {
            x: self.x + other.x,
            y: self.y + other.y,
            z: self.z + other.z,
        }
    }

    fn __sub__(&self, other: &Vec3) -> Vec3 {
        Vec3 {
            x: self.x - other.x,
            y: self.y - other.y,
            z: self.z - other.z,
        }
    }

    fn length(&self) -> f64 {
        (self.x * self.x + self.y * self.y + self.z * self.z).sqrt()
    }

    fn normalized(&self) -> Vec3 {
        let len = self.length();
        if len < 1e-15 {
            return self.clone();
        }
        Vec3 {
            x: self.x / len,
            y: self.y / len,
            z: self.z / len,
        }
    }

    fn dot(&self, other: &Vec3) -> f64 {
        self.x * other.x + self.y * other.y + self.z * other.z
    }

    fn cross(&self, other: &Vec3) -> Vec3 {
        Vec3 {
            x: self.y * other.z - self.z * other.y,
            y: self.z * other.x - self.x * other.z,
            z: self.x * other.y - self.y * other.x,
        }
    }

    fn as_tuple(&self) -> (f64, f64, f64) {
        (self.x, self.y, self.z)
    }
}

/// 4x4-style transform stored as rotation matrix + translation.
#[pyclass]
#[derive(Clone, Debug)]
pub struct Transform3D {
    rotation: [f64; 9],  // row-major 3x3
    translation: Vec3,
}

#[pymethods]
impl Transform3D {
    #[new]
    fn new() -> Self {
        Transform3D {
            rotation: [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            translation: Vec3::new(0.0, 0.0, 0.0),
        }
    }

    /// Create a translation transform.
    #[staticmethod]
    fn translate(x: f64, y: f64, z: f64) -> Self {
        let mut t = Transform3D::new();
        t.translation = Vec3::new(x, y, z);
        t
    }

    /// Create a rotation about the Z axis (degrees) — useful for 2D-compatible rotation.
    #[staticmethod]
    fn rotate_z(degrees: f64) -> Self {
        let rad = degrees.to_radians();
        let c = rad.cos();
        let s = rad.sin();
        Transform3D {
            rotation: [c, -s, 0.0, s, c, 0.0, 0.0, 0.0, 1.0],
            translation: Vec3::new(0.0, 0.0, 0.0),
        }
    }

    /// Create a rotation about the Y axis (degrees).
    #[staticmethod]
    fn rotate_y(degrees: f64) -> Self {
        let rad = degrees.to_radians();
        let c = rad.cos();
        let s = rad.sin();
        Transform3D {
            rotation: [c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c],
            translation: Vec3::new(0.0, 0.0, 0.0),
        }
    }

    /// Create a rotation about the X axis (degrees).
    #[staticmethod]
    fn rotate_x(degrees: f64) -> Self {
        let rad = degrees.to_radians();
        let c = rad.cos();
        let s = rad.sin();
        Transform3D {
            rotation: [1.0, 0.0, 0.0, 0.0, c, -s, 0.0, s, c],
            translation: Vec3::new(0.0, 0.0, 0.0),
        }
    }

    /// Apply this transform to a Vec3 point.
    fn apply(&self, point: &Vec3) -> Vec3 {
        let r = &self.rotation;
        Vec3 {
            x: r[0] * point.x + r[1] * point.y + r[2] * point.z + self.translation.x,
            y: r[3] * point.x + r[4] * point.y + r[5] * point.z + self.translation.y,
            z: r[6] * point.x + r[7] * point.y + r[8] * point.z + self.translation.z,
        }
    }

    /// Compose two transforms: self * other.
    fn compose(&self, other: &Transform3D) -> Transform3D {
        let a = Matrix3::from_row_slice(&self.rotation);
        let b = Matrix3::from_row_slice(&other.rotation);
        let ab = a * b;
        let t_a = Vector3::new(self.translation.x, self.translation.y, self.translation.z);
        let t_b = Vector3::new(other.translation.x, other.translation.y, other.translation.z);
        let t_ab = a * t_b + t_a;

        let mut rotation = [0.0; 9];
        for (i, val) in ab.iter().enumerate() {
            // nalgebra stores column-major, convert to row-major
            let row = i % 3;
            let col = i / 3;
            rotation[row * 3 + col] = *val;
        }

        Transform3D {
            rotation,
            translation: Vec3::new(t_ab.x, t_ab.y, t_ab.z),
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "Transform3D(t=[{:.3}, {:.3}, {:.3}])",
            self.translation.x, self.translation.y, self.translation.z
        )
    }
}

/// The optodraw Rust core module.
#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Vec3>()?;
    m.add_class::<Transform3D>()?;
    Ok(())
}

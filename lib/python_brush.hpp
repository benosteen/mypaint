/* brushlib - The MyPaint Brush Library
 * Copyright (C) 2011 Martin Renold <martinxyz@gmx.ch>
 *
 * Permission to use, copy, modify, and/or distribute this software for any
 * purpose with or without fee is hereby granted, provided that the above
 * copyright notice and this permission notice appear in all copies.
 *
 * THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
 * WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
 * MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
 * ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
 * WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
 * ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
 * OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
 */

class PythonBrush : public Brush {

public:
  // get state as numpy array
  PyObject * python_get_state ()
  {
    npy_intp dims = {STATE_COUNT};
    PyObject * data = PyArray_SimpleNew(1, &dims, NPY_FLOAT32);
    npy_float32 * data_p = (npy_float32*)PyArray_DATA(data);
    for (int i=0; i<STATE_COUNT; i++) {
      data_p[i] = get_state(i);
    }
    return data;
  }

  // set state from numpy array
  void python_set_state (PyObject * data)
  {
    assert(PyArray_NDIM(data) == 1);
    assert(PyArray_DIM(data, 0) == STATE_COUNT);
    assert(PyArray_ISCARRAY(data));
    npy_float32 * data_p = (npy_float32*)PyArray_DATA(data);
    for (int i=0; i<STATE_COUNT; i++) {
      set_state(i, data_p[i]);
    }
  }

  // same as stroke_to() but with exception handling, should an
  // exception happen in the surface code (eg. out-of-memory)
  PyObject* python_stroke_to (Surface * surface, float x, float y, float pressure, float xtilt, float ytilt, double dtime)
  {
    bool res = stroke_to (surface, x, y, pressure, xtilt, ytilt, dtime);
    if (PyErr_Occurred()) {
      return NULL;
    } else if (res) {
      Py_RETURN_TRUE;
    } else {
      Py_RETURN_FALSE;
    }
  }

};

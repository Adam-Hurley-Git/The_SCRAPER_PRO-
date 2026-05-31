from coverage import cell_size, subdivide


def test_subdivide_returns_four_quadrants() -> None:
    cells = subdivide(51.59, -4.03, 51.67, -3.89)

    assert len(cells) == 4
    assert cells[0] == (51.59, -4.03, 51.63, -3.96)
    assert cells[-1] == (51.63, -3.96, 51.67, -3.89)


def test_cell_size_uses_smallest_axis() -> None:
    assert cell_size((0.0, 0.0, 2.0, 3.0)) == 2.0

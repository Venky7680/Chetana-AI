/**
 * Checks the grid's compaction rules without a browser.
 *
 * The layout engine is pure — widgets in, widgets out — so the cases that are
 * tedious to reproduce by hand (drop a tile on an occupied cell; delete one
 * and watch the rest rise) are asserted here instead of discovered later.
 *
 * Run with: npm run check:layout
 */
import { strict as assert } from "node:assert";

const { settle, collides, standardLayout, widgetsOf, COLS } = await import("../lib/dashboard.ts");

const w = (i, x, y, width, h) => ({
  i, x, y, w: width, h, static: false, name: i, widgetType: "PRESET",
});

function assertNoOverlaps(items, label) {
  for (let i = 0; i < items.length; i++) {
    for (let j = i + 1; j < items.length; j++) {
      assert.ok(!collides(items[i], items[j]), `${label}: ${items[i].i} overlaps ${items[j].i}`);
    }
  }
}

// 1. A layout that is already clean is left exactly as it is.
{
  const out = settle([w("a", 0, 0, 12, 4), w("b", 12, 0, 12, 4)]);
  assert.deepEqual(out.map((o) => [o.i, o.x, o.y]), [["a", 0, 0], ["b", 12, 0]]);
}

// 2. Whatever goes in, nothing overlaps coming out.
{
  assertNoOverlaps(settle([w("a", 0, 0, 12, 4), w("b", 0, 0, 12, 4), w("c", 0, 0, 12, 4)]), "pile-up");
}

// 3. The drag case: the pinned widget holds its cell and the one already
//    there is displaced — not the other way round.
{
  const out = settle([w("a", 0, 0, 12, 4), w("dragged", 0, 0, 12, 4)], "dragged");
  assert.equal(out.find((o) => o.i === "dragged").y, 0, "the dragged widget should hold its row");
  assert.equal(out.find((o) => o.i === "a").y, 4, "the widget already there should move down");
}

// 4. Widgets float up into a gap, so deleting one does not leave a hole.
{
  const out = settle([w("a", 0, 0, 12, 4), w("b", 0, 20, 12, 4)]);
  assert.equal(out.find((o) => o.i === "b").y, 4, "b should rise to sit under a");
}

// 5. Columns are independent: a tall tile on the left must not drag a
//    right-hand tile down with it.
{
  const out = settle([w("tall", 0, 0, 12, 20), w("right", 12, 0, 12, 4)]);
  assert.equal(out.find((o) => o.i === "right").y, 0);
}

// 6. Settling is stable. An unstable pass would make the canvas creep on
//    every pointer move.
{
  const once = settle([w("a", 0, 3, 8, 4), w("b", 4, 1, 8, 4), w("c", 0, 0, 24, 2)]);
  assert.deepEqual(settle(once), once, "settle should be idempotent");
}

// 7. The starter layout is valid on the grid it ships for.
{
  const layout = standardLayout();
  assertNoOverlaps(settle(layout), "standard layout");
  for (const item of layout) {
    assert.ok(item.x + item.w <= COLS, `${item.name} runs off the grid`);
    assert.ok(item.chetanaChart, `${item.name} should be an analytics widget`);
  }
  assert.equal(new Set(layout.map((i) => i.i)).size, layout.length, "ids must be unique");
}

// 8. A config from Keep's column is read defensively — it is JSON nothing validates.
{
  assert.deepEqual(widgetsOf(null), []);
  assert.deepEqual(widgetsOf({ dashboard_config: { widgets: "not an array" } }), []);
  assert.equal(widgetsOf({ dashboard_config: { widgets: [w("a", 0, 0, 4, 4), { i: "junk" }] } }).length, 1);
}

console.log("layout: 8 checks passed");

import assert from "node:assert/strict";
import test from "node:test";

import {
  deleteHistoryRecords,
  fetchAllHistoryPages,
} from "../src/lib/history-actions.ts";

test("loads all history pages when the record count exceeds one page", async () => {
  const records = Array.from({ length: 156 }, (_, id) => ({ id }));
  const requestedPages = [];

  const loaded = await fetchAllHistoryPages(async (offset, limit) => {
    requestedPages.push([offset, limit]);
    return records.slice(offset, offset + limit);
  });

  assert.equal(loaded.length, 156);
  assert.deepEqual(loaded, records);
  assert.deepEqual(requestedPages, [[0, 100], [100, 100]]);
});

test("continues deleting records and reports individual failures", async () => {
  const attempted = [];
  const progress = [];
  const failure = new Error("delete failed");

  const result = await deleteHistoryRecords(
    [{ id: 1 }, { id: 2 }, { id: 3 }],
    async (id) => {
      attempted.push(id);
      if (id === 2) throw failure;
    },
    (index, total) => progress.push([index, total]),
  );

  assert.deepEqual(attempted, [1, 2, 3]);
  assert.deepEqual(result.deletedIds, [1, 3]);
  assert.equal(result.failures.length, 1);
  assert.equal(result.failures[0].id, 2);
  assert.equal(result.failures[0].error, failure);
  assert.deepEqual(progress, [[1, 3], [2, 3], [3, 3]]);
});

test("reports complete success only after every delete succeeds", async () => {
  const result = await deleteHistoryRecords(
    [{ id: 4 }, { id: 5 }],
    async () => undefined,
  );

  assert.deepEqual(result, { deletedIds: [4, 5], failures: [] });
});

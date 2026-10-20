export interface HistoryDeleteFailure {
  id: number;
  error: unknown;
}

export async function fetchAllHistoryPages<T>(
  fetchPage: (offset: number, limit: number) => Promise<T[]>,
  pageSize = 100,
): Promise<T[]> {
  const records: T[] = [];
  let offset = 0;

  while (true) {
    const page = await fetchPage(offset, pageSize);
    records.push(...page);
    if (page.length < pageSize) return records;
    offset += page.length;
  }
}

export async function deleteHistoryRecords(
  records: readonly { id: number }[],
  deleteRecord: (id: number) => Promise<unknown>,
  onProgress?: (index: number, total: number) => void,
): Promise<{ deletedIds: number[]; failures: HistoryDeleteFailure[] }> {
  const deletedIds: number[] = [];
  const failures: HistoryDeleteFailure[] = [];

  for (const [index, record] of records.entries()) {
    onProgress?.(index + 1, records.length);
    try {
      await deleteRecord(record.id);
      deletedIds.push(record.id);
    } catch (error) {
      failures.push({ id: record.id, error });
    }
  }

  return { deletedIds, failures };
}

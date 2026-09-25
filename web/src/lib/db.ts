import postgres from "postgres";

// 로컬 Postgres. 스키마는 Python 수집기(db/migrations)가 소유하고 여기서는 읽기만 한다.
const globalForSql = globalThis as unknown as { sql?: ReturnType<typeof postgres> };
export const sql =
  globalForSql.sql ?? (globalForSql.sql = postgres(process.env.DATABASE_URL ?? "postgresql://localhost/ctopen", { max: 5 }));

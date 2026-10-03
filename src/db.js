const { PrismaClient } = require('@prisma/client');

// Reuse a single Prisma client across the app (and across hot reloads in dev)
// to avoid exhausting database connections.
//
// connection_limit caps the pool size so a traffic spike doesn't exhaust
// the database's max connections. pool_timeout is how long a request waits
// for a free connection before giving up.
const databaseUrl = process.env.DATABASE_URL || '';
const separator = databaseUrl.includes('?') ? '&' : '?';
const pooledUrl = `${databaseUrl}${separator}connection_limit=20&pool_timeout=10`;

const prisma = new PrismaClient({
  datasources: {
    db: { url: pooledUrl },
  },
  log: process.env.NODE_ENV === 'development' ? ['warn', 'error'] : ['error'],
});

module.exports = prisma;

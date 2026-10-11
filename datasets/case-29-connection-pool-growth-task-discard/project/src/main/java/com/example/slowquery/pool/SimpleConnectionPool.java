package com.example.slowquery.pool;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 一个简化版数据库连接池：按需扩容（borrow 时若未达上限则异步补建连接）。
 * 扩容任务被提交到一个有界队列的单线程执行器。
 */
public class SimpleConnectionPool {

    private final String url;
    private final String username;
    private final String password;
    private final int maxSize;
    private final long borrowTimeoutMs;

    private final Deque<Connection> idle = new ArrayDeque<>();
    private final AtomicInteger allocated = new AtomicInteger(0);

    private final ThreadPoolExecutor addConnectionExecutor;

    public SimpleConnectionPool(String url, String username, String password, int maxSize,
                                int queueCapacity, int queueThreads, long borrowTimeoutMs) {
        this.url = url;
        this.username = username;
        this.password = password;
        this.maxSize = maxSize;
        this.borrowTimeoutMs = borrowTimeoutMs;
        this.addConnectionExecutor = new ThreadPoolExecutor(
                queueThreads, queueThreads, 0L, TimeUnit.MILLISECONDS,
                new ArrayBlockingQueue<>(queueCapacity),
                new ThreadPoolExecutor.DiscardPolicy());
    }

    public Connection borrow() throws SQLException {
        long deadline = System.currentTimeMillis() + borrowTimeoutMs;
        synchronized (this) {
            expandIfNeeded();
            while (true) {
                Connection connection = idle.pollFirst();
                if (connection != null) {
                    return connection;
                }
                long remaining = deadline - System.currentTimeMillis();
                if (remaining <= 0) {
                    throw new SQLException("获取连接超时（allocated=" + allocated.get()
                            + ", idle=" + idle.size() + ", max=" + maxSize + "）");
                }
                try {
                    wait(remaining);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    throw new SQLException("获取连接被中断", e);
                }
            }
        }
    }

    public void release(Connection connection) {
        synchronized (this) {
            idle.addLast(connection);
            notifyAll();
        }
    }

    private void expandIfNeeded() {
        if (allocated.get() >= maxSize) {
            return;
        }
        allocated.incrementAndGet();
        addConnectionExecutor.execute(this::addConnection);
    }

    private void addConnection() {
        try {
            Connection connection = DriverManager.getConnection(url, username, password);
            synchronized (this) {
                idle.addLast(connection);
                notifyAll();
            }
        } catch (SQLException e) {
            allocated.decrementAndGet();
            synchronized (this) {
                notifyAll();
            }
        }
    }

    public int getAllocated() {
        return allocated.get();
    }

    public int getMaxSize() {
        return maxSize;
    }

    public void close() {
        addConnectionExecutor.shutdownNow();
        synchronized (this) {
            for (Connection connection : idle) {
                try {
                    connection.close();
                } catch (SQLException ignored) {
                    // 关闭阶段忽略
                }
            }
            idle.clear();
        }
    }
}

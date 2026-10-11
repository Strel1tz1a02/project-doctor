package com.example.slowquery.service;

import com.example.slowquery.dto.IngestResultVO;
import com.example.slowquery.pool.SimpleConnectionPool;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

@Service
public class PooledIngestService {

    private final SimpleConnectionPool connectionPool;
    private final ExecutorService workerExecutor = Executors.newFixedThreadPool(64);
    private final long holdMillis;

    public PooledIngestService(SimpleConnectionPool connectionPool,
                               @Value("${app.pool.hold-millis}") long holdMillis) {
        this.connectionPool = connectionPool;
        this.holdMillis = holdMillis;
    }

    public IngestResultVO ingest(int workers) {
        long start = System.currentTimeMillis();
        CountDownLatch latch = new CountDownLatch(workers);
        AtomicInteger success = new AtomicInteger();
        AtomicInteger timedOut = new AtomicInteger();
        AtomicInteger failed = new AtomicInteger();

        for (int i = 0; i < workers; i++) {
            final int shard = i % 16;
            workerExecutor.submit(() -> {
                Connection connection = null;
                try {
                    connection = connectionPool.borrow();
                    try (PreparedStatement ps = connection.prepareStatement(
                            "SELECT COUNT(*) FROM task_events WHERE shard = ?")) {
                        ps.setInt(1, shard);
                        try (ResultSet rs = ps.executeQuery()) {
                            if (rs.next()) {
                                rs.getLong(1);
                            }
                        }
                    }
                    Thread.sleep(holdMillis);
                    success.incrementAndGet();
                } catch (SQLException e) {
                    if (e.getMessage() != null && e.getMessage().contains("超时")) {
                        timedOut.incrementAndGet();
                    } else {
                        failed.incrementAndGet();
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    failed.incrementAndGet();
                } finally {
                    if (connection != null) {
                        connectionPool.release(connection);
                    }
                    latch.countDown();
                }
            });
        }

        try {
            latch.await(60, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }

        IngestResultVO vo = new IngestResultVO();
        vo.setWorkers(workers);
        vo.setSuccess(success.get());
        vo.setTimedOut(timedOut.get());
        vo.setFailed(failed.get());
        vo.setElapsedMs(System.currentTimeMillis() - start);
        vo.setAllocated(connectionPool.getAllocated());
        vo.setMaxSize(connectionPool.getMaxSize());
        return vo;
    }
}

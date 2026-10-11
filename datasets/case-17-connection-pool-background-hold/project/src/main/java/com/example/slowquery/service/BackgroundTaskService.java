package com.example.slowquery.service;

import org.springframework.stereotype.Service;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

@Service
public class BackgroundTaskService {

    private static final int POLL_ROUNDS = 3;

    private final DataSource dataSource;

    public BackgroundTaskService(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    public String runBatch(int tasks, int pollIntervalMs) {
        ExecutorService executor = Executors.newFixedThreadPool(tasks);
        List<Future<String>> futures = new ArrayList<>();
        for (int i = 0; i < tasks; i++) {
            long taskId = i + 1;
            futures.add(executor.submit(() -> runTask(taskId, pollIntervalMs)));
        }
        StringBuilder summary = new StringBuilder();
        for (Future<String> future : futures) {
            try {
                summary.append(future.get()).append('\n');
            } catch (ExecutionException e) {
                summary.append("task failed: ").append(e.getCause().getMessage()).append('\n');
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                summary.append("task interrupted\n");
            }
        }
        executor.shutdown();
        return summary.toString();
    }

    public String runTask(long taskId, int pollIntervalMs) throws SQLException, InterruptedException {
        Connection connection = dataSource.getConnection();
        for (int round = 0; round < POLL_ROUNDS; round++) {
            Thread.sleep(pollIntervalMs);
        }
        try (PreparedStatement ps = connection.prepareStatement(
                "SELECT id, order_no, amount, status FROM orders ORDER BY id DESC LIMIT ?")) {
            ps.setInt(1, 200);
            try (ResultSet rs = ps.executeQuery()) {
                int count = 0;
                while (rs.next()) {
                    count++;
                }
                return "task " + taskId + ": rows=" + count;
            }
        } finally {
            connection.close();
        }
    }
}

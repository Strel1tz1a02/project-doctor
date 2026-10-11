package com.example.slowquery.init;

import org.springframework.boot.CommandLineRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;

@Component
public class DataInitRunner implements CommandLineRunner {

    private final JdbcTemplate jdbcTemplate;

    public DataInitRunner(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @Override
    public void run(String... args) {
        Integer count = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM audit_logs", Integer.class);
        if (count != null && count > 0) {
            return;
        }

        int logTotal = 200000;
        Random random = new Random(42);
        long now = System.currentTimeMillis();
        String[] services = {"auth-service", "order-service", "payment-service", "user-service", "gateway"};

        List<Object[]> rows = new ArrayList<>();
        for (int i = 1; i <= logTotal; i++) {
            int roll = random.nextInt(100);
            String level = roll < 2 ? "ERROR" : (roll < 10 ? "WARN" : (roll < 40 ? "DEBUG" : "INFO"));
            String serviceName = services[random.nextInt(services.length)];
            long createdAtMs = now - random.nextInt(365 * 24 * 3600) * 1000L;
            String traceId = "trace-" + random.nextInt(1000000);
            rows.add(new Object[]{serviceName, level, "event-" + i, traceId, createdAtMs});

            if (rows.size() >= 5000) {
                jdbcTemplate.batchUpdate(
                        "INSERT INTO audit_logs(service_name, level, message, trace_id, created_at_ms) VALUES (?, ?, ?, ?, ?)",
                        rows
                );
                rows.clear();
            }
        }

        if (!rows.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO audit_logs(service_name, level, message, trace_id, created_at_ms) VALUES (?, ?, ?, ?, ?)",
                    rows
            );
        }

        System.out.println("测试数据初始化完成：audit_logs=" + logTotal);
    }
}

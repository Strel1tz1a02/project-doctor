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
        Integer count = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM task_events", Integer.class);
        if (count != null && count > 0) {
            return;
        }

        int total = 200000;
        int shards = 16;
        Random random = new Random(42);
        long now = System.currentTimeMillis();

        List<Object[]> rows = new ArrayList<>();
        for (int i = 1; i <= total; i++) {
            int shard = random.nextInt(shards);
            String status = random.nextBoolean() ? "OK" : "FAIL";
            int payloadSize = 128 + random.nextInt(4096);
            long createdAtMs = now - random.nextInt(30 * 24 * 3600) * 1000L;
            rows.add(new Object[]{shard, status, payloadSize, createdAtMs});
            if (rows.size() >= 5000) {
                jdbcTemplate.batchUpdate(
                        "INSERT INTO task_events(shard, status, payload_size, created_at_ms) VALUES (?, ?, ?, ?)",
                        rows);
                rows.clear();
            }
        }
        if (!rows.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO task_events(shard, status, payload_size, created_at_ms) VALUES (?, ?, ?, ?)",
                    rows);
        }

        System.out.println("测试数据初始化完成：task_events=" + total + "，shards=" + shards);
    }
}

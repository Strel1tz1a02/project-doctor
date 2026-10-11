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
        Integer count = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM threads", Integer.class);
        if (count != null && count > 0) {
            return;
        }

        int threadTotal = 200000;
        Random random = new Random(42);
        long now = System.currentTimeMillis();

        List<Object[]> rows = new ArrayList<>();
        for (int i = 1; i <= threadTotal; i++) {
            long updatedAtMs = now - random.nextInt(365 * 24 * 3600) * 1000L;
            long recencyAtMs = updatedAtMs - random.nextInt(86400) * 1000L;
            rows.add(new Object[]{"thread-" + i, updatedAtMs, recencyAtMs});

            if (rows.size() >= 5000) {
                jdbcTemplate.batchUpdate(
                        "INSERT INTO threads(title, updated_at_ms, recency_at_ms) VALUES (?, ?, ?)",
                        rows
                );
                rows.clear();
            }
        }

        if (!rows.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO threads(title, updated_at_ms, recency_at_ms) VALUES (?, ?, ?)",
                    rows
            );
        }

        System.out.println("测试数据初始化完成：threads=" + threadTotal);
    }
}

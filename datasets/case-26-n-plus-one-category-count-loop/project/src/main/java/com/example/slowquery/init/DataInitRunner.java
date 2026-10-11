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
        Integer count = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM orders", Integer.class);
        if (count != null && count > 0) {
            return;
        }

        int orderTotal = 200000;
        int categoryCount = 100;
        Random random = new Random(42);
        long now = System.currentTimeMillis();

        List<Object[]> rows = new ArrayList<>();
        for (int i = 1; i <= orderTotal; i++) {
            String category = "cat-" + String.format("%03d", 1 + random.nextInt(categoryCount));
            long amount = 100 + random.nextInt(9900);
            long createdAtMs = now - random.nextInt(365 * 24 * 3600) * 1000L;
            rows.add(new Object[]{category, amount, createdAtMs});

            if (rows.size() >= 5000) {
                jdbcTemplate.batchUpdate(
                        "INSERT INTO orders(category, amount, created_at_ms) VALUES (?, ?, ?)",
                        rows
                );
                rows.clear();
            }
        }

        if (!rows.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO orders(category, amount, created_at_ms) VALUES (?, ?, ?)",
                    rows
            );
        }

        System.out.println("测试数据初始化完成：orders=" + orderTotal + "，categories=" + categoryCount);
    }
}

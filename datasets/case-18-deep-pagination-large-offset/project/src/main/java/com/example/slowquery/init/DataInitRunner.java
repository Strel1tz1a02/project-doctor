package com.example.slowquery.init;

import org.springframework.boot.CommandLineRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.sql.Timestamp;
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
        Integer itemCount = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM items", Integer.class);
        if (itemCount != null && itemCount > 0) {
            return;
        }

        int itemTotal = 1200000;
        Random random = new Random(42);

        String[] categories = {"BOOK", "TOY", "FOOD", "TOOL", "GAME"};
        long now = System.currentTimeMillis();
        List<Object[]> items = new ArrayList<>();
        for (int i = 1; i <= itemTotal; i++) {
            String name = "item-" + i;
            String category = categories[random.nextInt(categories.length)];
            BigDecimal price = BigDecimal.valueOf(random.nextInt(100000) * 100.0);
            Timestamp createdAt = new Timestamp(now - random.nextInt(365 * 24 * 3600) * 1000L);

            items.add(new Object[]{name, category, price, createdAt});

            if (items.size() >= 5000) {
                jdbcTemplate.batchUpdate(
                        "INSERT INTO items(name, category, price, created_at) VALUES (?, ?, ?, ?)",
                        items
                );
                items.clear();
            }
        }

        if (!items.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO items(name, category, price, created_at) VALUES (?, ?, ?, ?)",
                    items
            );
        }

        System.out.println("测试数据初始化完成：items=" + itemTotal);
    }
}

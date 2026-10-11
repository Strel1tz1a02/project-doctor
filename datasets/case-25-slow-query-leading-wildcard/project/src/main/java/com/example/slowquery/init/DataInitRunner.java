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
        Integer count = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM articles", Integer.class);
        if (count != null && count > 0) {
            return;
        }

        int articleTotal = 200000;
        Random random = new Random(42);
        long now = System.currentTimeMillis();
        String[] words = {"spring", "boot", "query", "index", "mysql", "cache", "pool", "thread", "reactor", "gateway"};

        List<Object[]> rows = new ArrayList<>();
        for (int i = 1; i <= articleTotal; i++) {
            StringBuilder title = new StringBuilder();
            int wordCount = 3 + random.nextInt(4);
            for (int w = 0; w < wordCount; w++) {
                if (w > 0) {
                    title.append(' ');
                }
                title.append(words[random.nextInt(words.length)]);
            }
            title.append(" #").append(i);
            String content = "article-body-" + i + "-" + random.nextLong();
            long publishedAtMs = now - random.nextInt(730 * 24 * 3600) * 1000L;
            rows.add(new Object[]{title.toString(), content, publishedAtMs});

            if (rows.size() >= 5000) {
                jdbcTemplate.batchUpdate(
                        "INSERT INTO articles(title, content, published_at_ms) VALUES (?, ?, ?)",
                        rows
                );
                rows.clear();
            }
        }

        if (!rows.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO articles(title, content, published_at_ms) VALUES (?, ?, ?)",
                    rows
            );
        }

        System.out.println("测试数据初始化完成：articles=" + articleTotal);
    }
}

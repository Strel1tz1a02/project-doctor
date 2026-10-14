package com.example.slowquery.init;

import org.springframework.boot.CommandLineRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

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
        Integer articleCount = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM articles", Integer.class);
        if (articleCount != null && articleCount > 0) {
            return;
        }

        int authorTotal = 50000;
        int articleTotal = 200000;
        Random random = new Random(42);

        Integer authorCount = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM authors", Integer.class);
        if (authorCount == null || authorCount == 0) {
            List<Object[]> authors = new ArrayList<>();
            for (int i = 1; i <= authorTotal; i++) {
                authors.add(new Object[]{"author" + i, "author" + i + "@example.com"});
                if (authors.size() >= 5000) {
                    jdbcTemplate.batchUpdate("INSERT INTO authors(name, email) VALUES (?, ?)", authors);
                    authors.clear();
                }
            }
            if (!authors.isEmpty()) {
                jdbcTemplate.batchUpdate("INSERT INTO authors(name, email) VALUES (?, ?)", authors);
            }
        }

        String[] statuses = {"DRAFT", "PUBLISHED", "ARCHIVED", "REVIEW"};
        long now = System.currentTimeMillis();
        List<Object[]> articles = new ArrayList<>();
        for (int i = 1; i <= articleTotal; i++) {
            long authorId = random.nextInt(authorTotal) + 1;
            String status = statuses[random.nextInt(statuses.length)];
            Timestamp createdAt = new Timestamp(now - random.nextInt(365 * 24 * 3600) * 1000L);

            articles.add(new Object[]{authorId, "文章" + i, status, "摘要" + i, createdAt});

            if (articles.size() >= 5000) {
                jdbcTemplate.batchUpdate(
                        "INSERT INTO articles(author_id, title, status, summary, created_at) VALUES (?, ?, ?, ?, ?)",
                        articles
                );
                articles.clear();
            }
        }

        if (!articles.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO articles(author_id, title, status, summary, created_at) VALUES (?, ?, ?, ?, ?)",
                    articles
            );
        }

        System.out.println("测试数据初始化完成：authors=" + authorTotal + ", articles=" + articleTotal);
    }
}

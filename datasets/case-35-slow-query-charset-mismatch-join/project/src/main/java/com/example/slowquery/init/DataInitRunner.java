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

        int authorTotal = 50000;
        int articleTotal = 300000;
        Random random = new Random(42);
        long now = System.currentTimeMillis();
        String[] names = {"lin", "chen", "wang", "zhao", "liu", "sun", "zhou", "wu"};

        List<Object[]> authors = new ArrayList<>();
        for (int i = 1; i <= authorTotal; i++) {
            String authorCode = String.format("A%06d", i);
            String name = names[random.nextInt(names.length)];
            authors.add(new Object[]{authorCode, name});

            if (authors.size() >= 5000) {
                jdbcTemplate.batchUpdate(
                        "INSERT INTO authors(author_code, name) VALUES (?, ?)",
                        authors
                );
                authors.clear();
            }
        }
        if (!authors.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO authors(author_code, name) VALUES (?, ?)",
                    authors
            );
        }

        List<Object[]> articles = new ArrayList<>();
        for (int i = 1; i <= articleTotal; i++) {
            String articleCode = String.format("ART%09d", i);
            String title = "article-" + i;
            String authorCode = String.format("A%06d", 1 + random.nextInt(authorTotal));
            long createdAtMs = now - random.nextInt(365 * 24 * 3600) * 1000L;
            articles.add(new Object[]{articleCode, title, authorCode, createdAtMs});

            if (articles.size() >= 5000) {
                jdbcTemplate.batchUpdate(
                        "INSERT INTO articles(article_code, title, author_code, created_at_ms) VALUES (?, ?, ?, ?)",
                        articles
                );
                articles.clear();
            }
        }
        if (!articles.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO articles(article_code, title, author_code, created_at_ms) VALUES (?, ?, ?, ?)",
                    articles
            );
        }

        System.out.println("测试数据初始化完成：authors=" + authorTotal + ", articles=" + articleTotal);
    }
}

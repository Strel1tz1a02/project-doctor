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
        Integer products = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM products", Integer.class);
        if (products != null && products > 0) {
            return;
        }

        int categoryTotal = 2000;
        int brandTotal = 500;
        int productTotal = 200000;
        Random random = new Random(42);
        long now = System.currentTimeMillis();

        List<Object[]> categoryRows = new ArrayList<>();
        for (int i = 1; i <= categoryTotal; i++) {
            categoryRows.add(new Object[]{"category-" + i});
        }
        jdbcTemplate.batchUpdate("INSERT INTO categories(name) VALUES (?)", categoryRows);

        List<Object[]> brandRows = new ArrayList<>();
        for (int i = 1; i <= brandTotal; i++) {
            brandRows.add(new Object[]{"brand-" + i});
        }
        jdbcTemplate.batchUpdate("INSERT INTO brands(name) VALUES (?)", brandRows);

        List<Object[]> productRows = new ArrayList<>();
        for (int i = 1; i <= productTotal; i++) {
            long categoryId = 1 + random.nextInt(categoryTotal);
            long brandId = 1 + random.nextInt(brandTotal);
            long createdAtMs = now - random.nextInt(365 * 24 * 3600) * 1000L;
            productRows.add(new Object[]{categoryId, brandId, "product-" + i, createdAtMs});
            if (productRows.size() >= 5000) {
                jdbcTemplate.batchUpdate("INSERT INTO products(category_id, brand_id, name, created_at_ms) VALUES (?, ?, ?, ?)", productRows);
                productRows.clear();
            }
        }
        if (!productRows.isEmpty()) {
            jdbcTemplate.batchUpdate("INSERT INTO products(category_id, brand_id, name, created_at_ms) VALUES (?, ?, ?, ?)", productRows);
        }

        System.out.println("测试数据初始化完成：categories=" + categoryTotal + "，brands=" + brandTotal + "，products=" + productTotal);
    }
}

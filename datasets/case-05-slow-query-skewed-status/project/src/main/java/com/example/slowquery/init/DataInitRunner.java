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
        Integer orderCount = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM orders", Integer.class);
        if (orderCount != null && orderCount > 0) {
            return;
        }

        int orderTotal = 200000;
        Random random = new Random(42);
        // 状态分布倾斜：PAID 占 80%，其余取值占比很小
        String[] statuses = {
                "PAID", "PAID", "PAID", "PAID", "PAID",
                "PAID", "PAID", "PAID", "CREATED", "SHIPPED"
        };
        long now = System.currentTimeMillis();

        List<Object[]> orders = new ArrayList<>();
        for (int i = 1; i <= orderTotal; i++) {
            long userId = random.nextInt(50000) + 1;
            BigDecimal amount = BigDecimal.valueOf(random.nextInt(100000) * 100.0);
            String status = statuses[random.nextInt(statuses.length)];
            Timestamp createdAt = new Timestamp(now - random.nextInt(365 * 24 * 3600) * 1000L);

            orders.add(new Object[]{userId, "NO" + i, amount, status, "备注" + i, createdAt});

            if (orders.size() >= 5000) {
                jdbcTemplate.batchUpdate(
                        "INSERT INTO orders(user_id, order_no, amount, status, remark, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        orders
                );
                orders.clear();
            }
        }

        if (!orders.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO orders(user_id, order_no, amount, status, remark, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    orders
            );
        }

        System.out.println("测试数据初始化完成：orders=" + orderTotal);
    }
}

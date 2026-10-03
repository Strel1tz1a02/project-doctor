package com.example.slowquery.init;

import org.springframework.boot.CommandLineRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
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
        Integer userCount = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM users", Integer.class);
        if (userCount != null && userCount > 0) {
            markReady();
            return;
        }

        int userTotal = 50000;
        int orderTotal = 200000;
        Random random = new Random(42);
        String[] statuses = {"CREATED", "PAID", "SHIPPED", "DONE", "CANCELED"};

        // 插入用户
        List<Object[]> users = new ArrayList<>();
        for (int i = 1; i <= userTotal; i++) {
            users.add(new Object[]{"user" + i + "@example.com", "用户" + i});
            if (users.size() >= 5000) {
                jdbcTemplate.batchUpdate(
                        "INSERT INTO users(email, name, created_at) VALUES (?, ?, NOW())",
                        users
                );
                users.clear();
            }
        }
        if (!users.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO users(email, name, created_at) VALUES (?, ?, NOW())",
                    users
            );
        }

        // 插入订单
        List<Object[]> orders = new ArrayList<>();
        long now = System.currentTimeMillis();

        for (int i = 1; i <= orderTotal; i++) {
            long userId = random.nextInt(userTotal) + 1;
            BigDecimal amount = BigDecimal.valueOf(random.nextInt(100000) * 100.0);
            String status = statuses[random.nextInt(statuses.length)];
            Timestamp createdAt = new Timestamp(
                    now - random.nextInt(365 * 24 * 3600) * 1000L
            );

            orders.add(new Object[]{
                    userId,
                    "NO" + i,
                    amount,
                    status,
                    "备注" + i,
                    createdAt
            });

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

        System.out.println("测试数据初始化完成：users=" + userTotal + ", orders=" + orderTotal);
        markReady();
    }

    /**
     * 写出就绪标记文件，供容器健康检查判断种子数据是否初始化完成。
     * 只有当 DB 可连接、Tomcat 已监听、种子数据全部写完时才调用。
     */
    private void markReady() {
        try {
            Files.writeString(Paths.get("/tmp/ready"), "ready", StandardCharsets.UTF_8);
        } catch (Exception e) {
            System.err.println("写就绪标记失败：" + e.getMessage());
        }
    }
}

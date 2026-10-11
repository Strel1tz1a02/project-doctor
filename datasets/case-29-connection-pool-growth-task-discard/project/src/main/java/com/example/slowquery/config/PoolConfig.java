package com.example.slowquery.config;

import com.example.slowquery.pool.SimpleConnectionPool;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class PoolConfig {

    @Value("${spring.datasource.url}")
    private String url;

    @Value("${spring.datasource.username}")
    private String username;

    @Value("${spring.datasource.password}")
    private String password;

    @Value("${app.pool.max-size}")
    private int maxSize;

    @Value("${app.pool.queue-capacity}")
    private int queueCapacity;

    @Value("${app.pool.queue-threads}")
    private int queueThreads;

    @Value("${app.pool.borrow-timeout-ms}")
    private long borrowTimeoutMs;

    @Bean(destroyMethod = "close")
    public SimpleConnectionPool simpleConnectionPool() {
        return new SimpleConnectionPool(url, username, password, maxSize,
                queueCapacity, queueThreads, borrowTimeoutMs);
    }
}

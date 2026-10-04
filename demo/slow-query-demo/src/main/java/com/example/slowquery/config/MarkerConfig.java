package com.example.slowquery.config;

import com.example.slowquery.marker.RequestIdFilter;
import com.example.slowquery.marker.SqlCommentInterceptor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 注册请求关联过滤器与 SQL 标记拦截器。Spring Boot 会自动注册 Filter 类型的 Bean，
 * mybatis-spring-boot-starter 会自动把 Interceptor 类型的 Bean 装配进 SqlSessionFactory。
 */
@Configuration
public class MarkerConfig {

    @Bean
    public RequestIdFilter requestIdFilter() {
        return new RequestIdFilter();
    }

    @Bean
    public SqlCommentInterceptor sqlCommentInterceptor() {
        return new SqlCommentInterceptor();
    }
}

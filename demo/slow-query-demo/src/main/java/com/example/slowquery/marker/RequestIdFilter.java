package com.example.slowquery.marker;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * 从请求头读取 {@code X-Project-Doctor-Request-Id}，写入线程上下文，请求结束后清理。
 */
public class RequestIdFilter extends OncePerRequestFilter {

    public static final String HEADER = "X-Project-Doctor-Request-Id";

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        try {
            RequestContext.setRequestId(request.getHeader(HEADER));
            chain.doFilter(request, response);
        } finally {
            RequestContext.clear();
        }
    }
}

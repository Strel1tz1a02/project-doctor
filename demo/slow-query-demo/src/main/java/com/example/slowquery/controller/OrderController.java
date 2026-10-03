package com.example.slowquery.controller;

import com.example.slowquery.dto.OrderVO;
import com.example.slowquery.service.OrderService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/orders")
public class OrderController {

    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @GetMapping("/search")
    public Map<String, Object> search(@RequestParam String email,
                                      @RequestParam String status,
                                      @RequestParam(defaultValue = "1") int page,
                                      @RequestParam(defaultValue = "20") int size) {
        List<OrderVO> list = orderService.searchSlow(email, status, page, size);
        long total = orderService.countSlow(email, status);

        return Map.of(
                "total", total,
                "page", page,
                "size", size,
                "list", list
        );
    }
}

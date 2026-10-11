package com.example.slowquery.controller;

import com.example.slowquery.model.Order;
import com.example.slowquery.service.OrderService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/orders")
public class OrderController {

    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @GetMapping("/search")
    public List<Order> search(@RequestParam(defaultValue = "1000") long userId,
                              @RequestParam(defaultValue = "PAID") String status,
                              @RequestParam(defaultValue = "50") int limit) {
        return orderService.search(userId, status, limit);
    }
}

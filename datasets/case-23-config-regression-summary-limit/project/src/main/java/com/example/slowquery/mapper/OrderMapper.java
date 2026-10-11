package com.example.slowquery.mapper;

import com.example.slowquery.model.Order;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface OrderMapper {

    @Select(
        "SELECT id, user_id, order_no, amount, status, created_at " +
        "FROM orders " +
        "WHERE user_id = #{userId} " +
        "ORDER BY created_at DESC " +
        "LIMIT #{size}"
    )
    List<Order> findOrdersByUser(@Param("userId") Long userId,
                                 @Param("size") int size);

    @Select(
        "SELECT id, user_id, order_no, amount, status, created_at " +
        "FROM orders " +
        "ORDER BY id DESC " +
        "LIMIT #{limit}"
    )
    List<Order> findRecent(@Param("limit") int limit);
}

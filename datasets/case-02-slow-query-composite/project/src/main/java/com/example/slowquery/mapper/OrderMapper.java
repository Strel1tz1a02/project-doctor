package com.example.slowquery.mapper;

import com.example.slowquery.model.Order;
import com.example.slowquery.model.User;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface OrderMapper {

    @Select(
        "SELECT o.* " +
        "FROM orders o " +
        "WHERE o.status = #{status} " +
        "  AND o.user_id IN (" +
        "      SELECT id FROM users WHERE email LIKE CONCAT('%', #{email}, '%')" +
        "  ) " +
        "ORDER BY o.created_at DESC " +
        "LIMIT #{offset}, #{size}"
    )
    List<Order> findSlowOrders(@Param("email") String email,
                               @Param("status") String status,
                               @Param("offset") int offset,
                               @Param("size") int size);

    @Select(
        "SELECT COUNT(*) " +
        "FROM orders o " +
        "WHERE o.status = #{status} " +
        "  AND o.user_id IN (" +
        "      SELECT id FROM users WHERE email LIKE CONCAT('%', #{email}, '%')" +
        "  )"
    )
    long countSlowOrders(@Param("email") String email,
                         @Param("status") String status);

    @Select("SELECT * FROM users WHERE id = #{id}")
    User findUserById(@Param("id") Long id);
}

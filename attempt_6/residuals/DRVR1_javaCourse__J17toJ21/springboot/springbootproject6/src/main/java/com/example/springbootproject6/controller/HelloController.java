package com.example.springbootproject6.controller;

import org.springframework.web.bind.annotation.RestController;

import com.example.springbootproject6.entity.AppUser;
import com.example.springbootproject6.jwt.JwtService;
import com.example.springbootproject6.service.UserService;

import jakarta.servlet.http.HttpServletRequest;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.security.core.Authentication;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

// http://localhost:8080/swagger-ui/index.html

@RestController
public class HelloController {

    @Autowired
    UserService userService;

    @GetMapping("/")
    public String greet(HttpServletRequest request) {
        return "Hello world! ";
    }

    @PostMapping("/register")
    public AppUser register(@RequestBody AppUser user) {
        return userService.save(user);
    }

    @Autowired
    AuthenticationManager authenticationManager;

    @Autowired
    JwtService jwtService;

    @PostMapping("/login")
    public String login(@RequestBody AppUser user) {

        // Antes de generar un token correspondiente al nombre de usuario, debemos
        // validar que las credenciales sean correctas. auth manager va a acceder al
        // UserDetailsService para validar esto.
        Authentication auth = authenticationManager
                .authenticate(new UsernamePasswordAuthenticationToken(user.getUsername(), user.getPassword()));

        if (auth.isAuthenticated()) {
            return jwtService.generateToken(user.getUsername());
        } else {
            return "Not logged";
        }
    }

}

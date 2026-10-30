document.getElementById("login-btn").addEventListener("click", function () {
  var email = document.getElementById("email").value;
  document.getElementById("message").textContent = email ? "Welcome, " + email : "Please enter your email";
});
